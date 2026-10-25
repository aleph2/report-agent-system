"""Exercise the registered visual tool on fresh synthetic scan/image inputs only."""

import asyncio
import argparse
from io import BytesIO
import json
from pathlib import Path
import secrets

from PIL import Image, ImageDraw, ImageFont

from report_agent.catalog import Catalog
from report_agent.deep_runtime import business_tools
from report_agent.store import Store
from report_agent.workspace import Workspace
from run_deepagents_trial import load_service_environment


async def main(output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    intent = {'model': 'deepseek-v4.1-flash', 'scope': 'synthetic scan OCR and cropped image observation',
              'status': 'intent', 'report_resume': False, 'engineering_sources': False}
    (root / 'intent.json').write_text(json.dumps(intent), encoding='utf-8')
    load_service_environment('hunan-highway-trial067-api-1')
    nonce = secrets.token_hex(4).upper()
    im = Image.new('RGB', (1100, 800), 'white')
    draw = ImageDraw.Draw(im)
    font_path = '/mnt/c/Windows/Fonts/msyh.ttc'
    if not Path(font_path).exists():
        font_path = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    font = ImageFont.truetype(font_path, 40)
    for i, line in enumerate([f'ID: {nonce}', 'Item        Height', 'A              28.9 m', 'B              38.0 m']):
        draw.text((50, 40 + i * 80), line, font=font, fill='black')
    draw.rectangle((100, 440, 310, 650), fill='red')
    draw.ellipse((700, 440, 910, 650), fill='blue')
    png, pdf = BytesIO(), BytesIO()
    im.save(png, format='PNG')
    im.save(pdf, format='PDF', resolution=144)
    store = Store(root)
    store.initialize({'goal': 'Test optional image observations, no engineering report.',
                      'sources': [{'id': 'instructions', 'title': 'Synthetic test', 'coverage': 'complete',
                                   'content': 'Inspect only the supplied synthetic inputs.'}]})
    ws = Workspace(store)
    ws.initialize()
    catalog = Catalog(store)
    scan = catalog.import_file('synthetic-scan.pdf', pdf.getvalue())['source']['id']
    picture = catalog.import_file('synthetic-image.png', png.getvalue())['source']['id']
    before = catalog.sources()
    assert catalog.read(scan)['total_blocks'] == 0
    assert catalog.read(picture)['total_blocks'] == 0
    tool = next(t for t in business_tools(ws, 'knowledge', None, None)
                if t.__name__ == 'analyze_source_image')
    q = 'Transcribe the visible ID and the Item/Height table, preserving rows and units. Mark uncertainty.'
    ocr = await tool(scan, q)
    cached = await tool(scan, q)
    visual = await tool(picture, 'Describe the shapes and colors on the left and right of this region.',
                        crop=[0, .5, 1, 1])
    text = ocr.get('observation', '')
    result = {'ocr': ocr, 'cropped_visual': visual,
              'checks': {'image_only_nonce_found': nonce in text,
                         'both_values_found': '28.9' in text and '38.0' in text,
                         'same_request_reused': cached.get('reused') is True,
                         'sources_and_ocr_unchanged': before == catalog.sources(),
                         'no_published_results': ws.results() == [],
                         'logical_vision_requests': sum(e['kind'] == 'vision_request' for e in store.events())},
              'limitations': 'Synthetic tool integration only, not engineering drawing accuracy or autonomous report acceptance.'}
    (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    asyncio.run(main(args.output))
