"""Подбор модели Ranvik: что читает картинки и реально отвечает на фото с уравнением."""
from __future__ import annotations

import asyncio
import base64
import io
import json

import aiohttp
from PIL import Image, ImageDraw, ImageFont

import config

KEY = config.AI_API_KEY
BASE = "https://api.ranvik.ru/v1"


def make_image() -> str:
    img = Image.new("RGB", (900, 300), "white")
    d = ImageDraw.Draw(img)
    try:
        big = ImageFont.truetype("arial.ttf", 46)
        small = ImageFont.truetype("arial.ttf", 28)
    except Exception:  # noqa: BLE001
        big = small = ImageFont.load_default()
    d.text((40, 30), "Решите уравнение:", fill="black", font=small)
    d.text((40, 110), "5(x - 2) = 3x + 1", fill="black", font=big)
    d.text((40, 220), "8 класс, алгебра", fill="gray", font=small)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


async def text_chat(session, model: str) -> tuple[int, str]:
    payload = {"model": model, "max_tokens": 40,
               "messages": [{"role": "user", "content": "Реши: 2x + 3 = 7. Кратко."}]}
    try:
        async with session.post(f"{BASE}/chat/completions", json=payload,
                                headers={"Authorization": f"Bearer {KEY}"},
                                timeout=aiohttp.ClientTimeout(total=60)) as r:
            body = await r.text()
            if r.status == 200:
                data = json.loads(body)
                return 200, str(data["choices"][0]["message"]["content"])[:160]
            return r.status, body[:120]
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__


async def vision_chat(session, model: str, image_b64: str) -> tuple[int, str]:
    payload = {"model": model, "max_tokens": 500, "messages": [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Что на фото? Реши уравнение по шагам. Ответь JSON "
                                     '{"what":"","steps":[],"answer":"","hint":"","similar":""}'},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ],
    }]}
    try:
        async with session.post(f"{BASE}/chat/completions", json=payload,
                                headers={"Authorization": f"Bearer {KEY}"},
                                timeout=aiohttp.ClientTimeout(total=90)) as r:
            body = await r.text()
            if r.status == 200:
                data = json.loads(body)
                return 200, str(data["choices"][0]["message"]["content"])[:400]
            return r.status, body[:150]
    except Exception as exc:  # noqa: BLE001
        return 0, type(exc).__name__


async def main() -> None:
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{BASE}/models", headers={"Authorization": f"Bearer {KEY}"},
                         timeout=aiohttp.ClientTimeout(total=30)) as r:
            data = await r.json()
        models = data.get("data", [])
        print(f"моделей: {len(models)}\n")
        if models:
            print("поля модели:", ", ".join(sorted(models[0].keys()))[:300], "\n")

        vision_hint = [m for m in models
                       if any(k in json.dumps(m, ensure_ascii=False).lower()
                              for k in ('"vision": true', '"image"', "multimodal", '"vision":true'))]
        print(f"с признаком картинок: {len(vision_hint)}")
        for m in vision_hint[:8]:
            print("  ·", m.get("id"))

        image_b64 = make_image()
        candidates = [m.get("id") for m in (vision_hint or models)][:4]
        for extra in ("gemini-2.5-flash", "gpt-4.1-mini", "gpt-4o-mini"):
            if extra not in candidates:
                candidates.append(extra)

        found = None
        for model in candidates:
            st, info = await text_chat(s, model)
            print(f"\n— {model}: текст {st} {info[:80]}")
            if st != 200:
                continue
            st2, info2 = await vision_chat(s, model, image_b64)
            ok = st2 == 200 and ("5" in info2)
            print(f"  фото: {st2} {info2[:200]}")
            if st2 == 200 and ok:
                found = model
                break

        print("\n" + "=" * 60)
        if found:
            print(f"РАБОЧАЯ ПАРА:\n  AI_BASE_URL={BASE}\n  AI_MODEL={found}")
        else:
            print("ни текст+фото подтвердить не удалось")


if __name__ == "__main__":
    asyncio.run(main())
