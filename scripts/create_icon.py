from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    assets = Path("assets")
    assets.mkdir(exist_ok=True)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    images = []
    for size in sizes:
        image = Image.new("RGBA", size, (24, 32, 44, 0))
        draw = ImageDraw.Draw(image)
        width, height = size
        line_width = max(1, width // 24)
        draw.rounded_rectangle(
            [1, 1, width - 2, height - 2],
            radius=max(3, width // 8),
            fill=(28, 46, 68, 255),
            outline=(56, 189, 248, 255),
            width=line_width,
        )
        draw.rectangle([width * 0.18, height * 0.30, width * 0.82, height * 0.72], fill=(245, 247, 250, 255))
        draw.rectangle([width * 0.25, height * 0.38, width * 0.74, height * 0.45], fill=(28, 46, 68, 255))
        draw.rectangle([width * 0.25, height * 0.52, width * 0.58, height * 0.59], fill=(28, 46, 68, 255))
        draw.ellipse([width * 0.62, height * 0.50, width * 0.75, height * 0.63], fill=(56, 189, 248, 255))
        images.append(image)

    images[-1].save(assets / "autosnap.ico", sizes=sizes)


if __name__ == "__main__":
    main()
