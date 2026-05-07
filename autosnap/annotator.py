from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

import requests

from .models import Annotation, CATEGORIES


ANNOTATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "category",
        "title",
        "summary",
        "tags",
        "ocr_text",
        "has_sensitive_info",
        "sensitive_types",
        "confidence",
    ],
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "title": {"type": "string", "maxLength": 40},
        "summary": {"type": "string", "maxLength": 160},
        "tags": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 24}},
        "ocr_text": {"type": "string", "maxLength": 4000},
        "has_sensitive_info": {"type": "boolean"},
        "sensitive_types": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["password", "id_card", "bank_card", "phone", "private_chat", "api_key", "other"],
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "additionalProperties": False,
}


class AnnotationService:
    def __init__(self, model: str = "gpt-4.1-mini", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def annotate(self, image_path: Path) -> Annotation | None:
        if not self.available:
            return None
        if self._looks_sensitive_by_name(image_path):
            return Annotation(
                category="id_doc",
                title="敏感截图",
                summary="文件名命中本地敏感规则，未上传到 AI。",
                tags=["sensitive", "local"],
                ocr_text="",
                has_sensitive_info=True,
                sensitive_types=["other"],
                confidence=0.8,
                model="local-rule",
            )
        try:
            return self._annotate_openai(image_path)
        except Exception:
            return None

    def _annotate_openai(self, image_path: Path) -> Annotation | None:
        mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        prompt = (
            "You are AutoSnap's screenshot annotator. Return a compact JSON annotation for one screenshot. "
            "Use the dominant language visible in the screenshot. Do not invent text. "
            f"Allowed categories: {', '.join(CATEGORIES)}."
        )
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {
                            "type": "input_image",
                            "image_url": f"data:{mime};base64,{image_b64}",
                            "detail": "low",
                        },
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "autosnap_annotation",
                    "schema": ANNOTATION_SCHEMA,
                    "strict": True,
                }
            },
        }
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        content = self._extract_text(data)
        if not content:
            return None
        raw = json.loads(content)
        return Annotation(
            category=self._clean_category(raw.get("category", "misc")),
            title=str(raw.get("title") or "")[:40],
            summary=str(raw.get("summary") or "")[:160],
            tags=[str(tag)[:24] for tag in raw.get("tags", [])[:8]],
            ocr_text=str(raw.get("ocr_text") or "")[:4000],
            has_sensitive_info=bool(raw.get("has_sensitive_info")),
            sensitive_types=[str(item) for item in raw.get("sensitive_types", [])],
            confidence=max(0.0, min(1.0, float(raw.get("confidence", 0.0)))),
            model=self.model,
        )

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str | None:
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                    return content["text"]
        return None

    @staticmethod
    def _clean_category(category: str) -> str:
        return category if category in CATEGORIES else "misc"

    @staticmethod
    def _looks_sensitive_by_name(path: Path) -> bool:
        text = path.name.lower()
        return bool(re.search(r"(password|secret|api[_-]?key|id[_-]?card|身份证|密码|银行卡)", text))
