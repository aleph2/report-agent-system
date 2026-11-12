"""Bounded current-account image probe; no project data, fallback or retries."""

import base64
import argparse
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets

from openai import OpenAI, APIStatusError
from PIL import Image, ImageDraw, ImageFont

from run_deepagents_trial import load_service_environment


def main(models, output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    receipt = root / 'vision-probe.json'
    # Never repeat an uncertain paid call just because this diagnostic was rerun.
    with receipt.open('x', encoding='utf-8') as handle:
        json.dump({'status': 'initializing'}, handle)
    load_service_environment('hunan-highway-trial067-api-1')
    nonce = secrets.token_hex(4).upper()
    im = Image.new('RGB', (800, 400), 'white')
    draw = ImageDraw.Draw(im)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 44)
    draw.text((45, 30), nonce, font=font, fill='black')
    draw.rectangle((70, 140, 240, 310), fill='red')
    draw.ellipse((480, 140, 650, 310), fill='blue')
    png = BytesIO()
    im.save(png, format='PNG')
    (root / 'synthetic-vision.png').write_bytes(png.getvalue())
    image_url = 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode('ascii')
    evidence = {'status': 'running', 'expected': {'text': nonce, 'left': 'red square',
                'right': 'blue circle'}, 'calls': []}

    def save():
        receipt.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')

    with OpenAI(base_url=os.environ['REPORT_BASE_URL'], api_key=os.environ['REPORT_API_KEY'],
                max_retries=0, timeout=60) as client:
        for model in models:
            call = {'model_requested': model, 'intent_at': datetime.now(timezone.utc).isoformat(),
                    'status': 'request_intent', 'retries': 0, 'synthetic_only': True}
            evidence['calls'].append(call)
            save()
            try:
                response = client.chat.completions.create(
                    model=model, max_tokens=512, stream=False,
                    messages=[{'role': 'user', 'content': [
                        {'type': 'text', 'text': 'Read the text in the image. Describe the left and right shapes and their colors. If you cannot see the image, say so.'},
                        {'type': 'image_url', 'image_url': {'url': image_url}},
                    ]}],
                )
                content = response.choices[0].message.content or ''
                call.update(status='response_received', model_returned=response.model,
                            response_id=response.id, content=content,
                            finish_reason=response.choices[0].finish_reason,
                            exact_text_found=nonce in content,
                            usage=response.usage.model_dump() if response.usage else None)
            except APIStatusError as exc:
                body = exc.body if isinstance(exc.body, dict) else {}
                error = body.get('error', body)
                error = error if isinstance(error, dict) else {}
                code = str(error.get('code', ''))
                message = str(error.get('message', ''))
                message = message.replace(os.environ['REPORT_API_KEY'], '[REDACTED]')
                message = message.replace(image_url, '[IMAGE]')
                message = re.sub(r'https?://\S+', '[URL]', message)
                call.update(status='http_rejected', http_status=exc.status_code,
                            error_type=type(exc).__name__, provider_code=code[:120],
                            provider_message=message[:700])
            except Exception as exc:
                call.update(status='outcome_unknown', error_type=type(exc).__name__)
                save()
                break
            call['finished_at'] = datetime.now(timezone.utc).isoformat()
            save()
    evidence['status'] = 'finished'
    save()
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', action='append', required=True,
                        choices=['deepseek-v4.1-flash-1017'])
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    main(args.model, args.output)
