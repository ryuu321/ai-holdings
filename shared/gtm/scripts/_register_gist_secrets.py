"""57製品の GIST_ID を GitHub Secrets に一括登録"""
import sys, os, json, time, urllib.request
from base64 import b64encode
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

for line in Path('C:/Users/ryuuM/ai-holdings/.env').read_text(encoding='utf-8').splitlines():
    k, _, v = line.partition('=')
    if v and k.strip() not in os.environ:
        os.environ[k.strip()] = v.strip()

from nacl import encoding, public

GIST_TOKEN = os.environ.get('GITHUB_TOKEN', '') or os.environ.get('GIST_TOKEN', '')
REPO = 'ryuu321/ai-holdings'

CREATED_GISTS = {
    'hakentext': '523a6cd10fbf009257132d395b335822',
    'hashitext': '426f2604fffac8b9641173b4cc65b60e',
    'hokentext': 'ec2ed3ee09111169ce14b6d529da8549',
    'ihintext': 'c022078fd8747942a5e8b5fd25794de8',
    'insatsutext': '59c9162f26da0c9c44606974487e7169',
    'iryokikitext': 'b50baf7a306e9b8d2ac30fd27d7a5087',
    'iryotext': 'dcec923be245d84ddc475df1b956cc40',
    'iyakuhintext': 'c992e8ed99378cb5a6f70f4655f14cd9',
    'juitext': '15d4b8bdae7d91434c149649fa88f193',
    'kaikeishitext': '0e99316eea22831531c1c0ddd15dbf40',
    'kaitaitext': 'ffae231788d014920c6447775b9f9e02',
    'kaiuntext': 'bbf423d1babe2e779c8975be17be590e',
    'kanteitext': '330ceb1e139bac2fbd209965f4a7a936',
    'keibitext': '7d72ab90f77d0d450115b27665688e4c',
    'kensetsuconstext': '28f4086309660d84bb652d70a763e964',
    'kogutext': '2490d3d52bfc57e02a80ea191e09c42f',
    'komutentext': '2d86011dee23419dd58e7c29e4e547ea',
    'kyoshujotext': 'c4249ad8a6bfd476e319dcac2b1472df',
    'kyuhaisuitext': 'dd5265e00caf94ef8d897b30ab06e2ca',
    'kyushokutext': '6e5c45f1f6ec08f588579bd540961038',
    'mokkotext': 'c3716514f2a86c863d12516beda214d9',
    'nailtext': 'bbdb893bc49c64075ff5622739952045',
    'naisotext': '7005e8b640e14e4ad4fa24717e01e916',
    'nokitext': '52087b4458541ea6448c322f3bc0106a',
    'nougyotext': '8f6208d9e01a9ba660b21af1a6dadbde',
    'pettotext': 'd87c9ec96392914d959df902be9105a2',
    'phototext': 'd753b4c313f2013b549a5fa6615db2d2',
    'reizotext': 'aa023fd473a6d57d356247930826568d',
    'ringyotext': 'f5e058c83b826808e9e948a8feba1a0f',
    'ryokantext': 'df528887be91fdef06ec4b37be658942',
    'salontext': 'e36e0cd8671b6bb01c14dffc08c09ba2',
    'sangyoitext': '0d6d0f4491f5c3951d4b8c97d883cdfb',
    'seibitext': 'dfbcf251b1257b3aabf9a5c1799fa0dc',
    'seishintext': 'f3210cc0d58b40d89680966bccf36010',
    'seisoutext': '16e9076182d6af233be08208a7905878',
    'sekizaitext': '9c1c90036310a3a109a777d50bfedf83',
    'senmontext': '77a22156072bb1fe859509d2bc7b3f84',
    'shindantext': 'f5dc0a676e06b7b5195830ceae81545f',
    'shinkyutext': 'edb96647014e3e487e63a6c962d2585c',
    'shogyotext': 'fabe3f4af5b5a3bf25dce87a056c3f21',
    'shokuhintext': '3889566ed2caa7f8a8a9a45e2729b7aa',
    'shurotext': '005bc47f663764f6d7f921b58b2b7cde',
    'shushokutext': '09340033b886c2a9bccaa366b132de77',
    'sogitext': '8157857ae8aa840e1af2b1a11349e930',
    'sokotext': '266049941c9c945f7b83842f0de1eb44',
    'sokuryotext': 'a513633b5ff9a3fb1e92a1680f20be62',
    'sonpohokentext': 'aed635c67af03479f83d6aafd2ac0725',
    'suisantext': 'af5b9dd9fbf34ad43a841140a281f1cf',
    'supertext': '96c03c5072fd69c33b02a4a2746adafc',
    'tenjikaitext': '8dfdf81dc350615294d214010c8dbe01',
    'unsotext': '92ca86313a958258b8638713ea3f664c',
    'yakuhintext': 'a1f5b6550e39aad4791fd109ca3a7028',
    'yakuzaishitext': '441909fac24a08c1bba25bc2f63db021',
    'yanetext': 'cf274c5881046fdb333a8a588d0c2214',
    'yunyutext': 'deed38c7a586f1d41a700ea36947f982',
    'yurohokentext': '11e997d965ed8172047ee0c8d67b0c46',
    'zoentext': 'e4a6530b83bafce4cce3b2c29f2f92bf',
}

def gh_req(method, path, data=None):
    url = f'https://api.github.com{path}'
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={
        'Authorization': f'token {GIST_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'X-GitHub-Api-Version': '2022-11-28',
    }, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        content = r.read()
        return json.loads(content) if content else {}

pub_key_data = gh_req('GET', f'/repos/{REPO}/actions/secrets/public-key')
key_id = pub_key_data['key_id']
box = public.SealedBox(public.PublicKey(pub_key_data['key'].encode(), encoding.Base64Encoder))

ok, ng = 0, []
for slug, gist_id in CREATED_GISTS.items():
    name = f'{slug.upper()}_SENT_LOG_GIST_ID'
    try:
        encrypted = b64encode(box.encrypt(gist_id.encode())).decode()
        gh_req('PUT', f'/repos/{REPO}/actions/secrets/{name}', {
            'encrypted_value': encrypted, 'key_id': key_id,
        })
        print(f'  ✓ {name}')
        ok += 1
        time.sleep(0.2)
    except Exception as e:
        print(f'  ✗ {slug}: {e}')
        ng.append(slug)

print(f'\n完了: {ok}/{len(CREATED_GISTS)} / 失敗: {len(ng)}')
