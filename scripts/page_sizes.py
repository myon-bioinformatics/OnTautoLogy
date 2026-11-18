"""Add artifact byte counts at the bottom of every published HTML page."""
from pathlib import Path
import re

root = Path(__file__).resolve().parent.parent / 'site'
pattern = re.compile(r'<!-- page-sizes -->.*?<!-- /page-sizes -->', re.S)
pages = {p: pattern.sub('', p.read_text()) for p in root.rglob('*.html')}
source_bytes = sum(len(pages[p].encode()) if p in pages else p.stat().st_size
                   for p in root.rglob('*') if p.is_file())
for _ in range(12):
    total = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    footer = ('<!-- page-sizes --><footer aria-label="配信容量" style="padding:1rem;font-size:.8rem;overflow-wrap:anywhere">'
              f'配信成果物 {total:,} bytes（{total / 1024:.1f} KiB） · '
              f'容量表示追加前 {source_bytes:,} bytes · 静的HTML/JS（コンパイルなし） · '
              'site内の全ファイル・非圧縮合計。転送圧縮・ブラウザ保存データを除く。'
              '</footer><!-- /page-sizes -->')
    for path, original in pages.items():
        updated = original.replace('</body>', footer + '</body>') if '</body>' in original else original + footer
        path.write_text(updated)
    if total == sum(p.stat().st_size for p in root.rglob('*') if p.is_file()):
        break
else:
    raise RuntimeError('artifact size did not stabilize')
print(f'Published artifact: {total} bytes, {len(pages)} pages')
