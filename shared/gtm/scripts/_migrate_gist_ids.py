"""
GIST ID移行スクリプト
- 全103製品のGist IDをgist_ids.jsonに保存
- 全ワークフローをSecrets参照→JSONファイル参照に一括更新
- 旧GIST_ID Secretsを削除
"""
import json, re, subprocess, sys, time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

REPO_ROOT = Path('C:/Users/ryuuM/ai-holdings')
WORKFLOWS_DIR = REPO_ROOT / '.github/workflows'
GIST_IDS_FILE = REPO_ROOT / 'shared/gtm/config/gist_ids.json'

# 全103製品のGist ID（GistAPI実行時に収集済み）
ALL_GIST_IDS = {
    'aftertext': '7ee2d1551d56b00586a91f6bb20a24e5',
    'bengoshitext': 'f7d74ca2ef2ee806f36418d4d173609d',
    'birutext': '3911127d0ae2af7dd4be8969b015c35d',
    'braidaltext': '9705f4c63cba2b014f7c978a7f3b53d6',
    'caretext': '72089480e0791fe8bed0179a0dea0e27',
    'chukotext': '665ee7bd517fdc5c4fddf2cd34477ef6',
    'churntext': 'c398d4cfa92f98f79cc77a0ef5fba8cb',
    'cmtext': '5d39cfd944abc6aa91025c75399e7232',
    'constext': '0483349ee4d7bb6b4e82f93032e1fff2',
    'daytext': '1951ffdca5fa714e85c81187918137e2',
    'deliverytext': '2e02d0bbc48b7b206394b97d69ca928b',
    'denkitext': 'a07f9779e4a80f00d6ae1cb0d4acf1b0',
    'dobokutext': 'ae6a1873587beab79ba890d40f9829d9',
    'drugtext': 'f2ee8ce8e6bdb9d3ec15631a3d609455',
    'eventtext': '6975239ebb6f9f691a3b3cff8c82b171',
    'extext': '0fa5be603b043e1fadb34cedd486735d',
    'fctext': '8d72e2d82e771e27393ca35d54bde944',
    'fittext': 'fa75bd401153b098b788b3a2224d308d',
    'flowertext': '1d177b621032805ed778b59f25a9abc8',
    'fptext': 'd7232ecd4fc6f619f345cf0e6a7a160c',
    'fudotext': '751321c2c82eefbd4c23cb74556aa01b',
    'fukushitext': '1530aa50b5a076b948289de658ecacd0',
    'gakudotext': '11d9a6ede5c71074500e63dc1bf5b376',
    'gasutext': '7ccc6faf17a757bf33bfaa4e37000e66',
    'ghtext': '0e3134ae191fe8ded77a1e358080e0b0',
    'gogakutext': 'a3520da8df9761b3de8bb17c7c476afe',
    'gyogyotext': 'bd2762255dd143b6cd5bdee8b4e674ca',
    'gyotext': 'c9c6fbb577d14d25e73b3325db8a3759',
    'haikantext': '3aead21d4ef4079fe1f17dbed0a75328',
    'haikitext': '1460e175bb3c3f85ab5e8bbfd94be3a0',
    'hakentext': '306fbc0f71623a6d01369148ca523be2',
    'hashitext': '844b83fe9f1d91fac540ef44994ee02a',
    'hoikutext': 'afcaa6f95d8a1bd3d536db118c9589ea',
    'hokentext': 'f864faa4d079250cb41b0ccf501957d1',
    'ihintext': '9f28cbb78040410d99bae088cf10d51b',
    'iintext': 'd840294ee22008e1ed3cfe808c4c6865',
    'insatsutext': '502fc71f374cd06bf219eaf430ca93dd',
    'iryokikitext': 'a6cecf47a273fd2095c0f97ebdcbb448',
    'iryotext': 'b6750da774c4010fedb2add97a2d25b9',
    'iyakuhintext': '618cd70db35cc2befcdb621213e7d584',
    'juitext': 'b8e36d722637101f257f0db585cd4fcb',
    'jukutext': '128423685f67e7b686ba2831ae7008b3',
    'kaikeishitext': '4268da93e8cb7c2c7571f99d739dd2b3',
    'kaitaitext': 'f3a9eb704cdfb1f69150c70f39c1a490',
    'kaiuntext': '96fc19ea3d7022d0c217d7ab44787053',
    'kangotext': 'bb996fd920651f007bdd4b5b5bf8ab10',
    'kanritext': 'aef590b4794fb9f0b410a749c693d79f',
    'kanteitext': '53d623c894dfb641f88110cbcc117623',
    'keibitext': 'db979745e1ca2b39054d62831815411c',
    'kensetsuconstext': 'f681bd48a13c6627c10ff4e6fe76ef8c',
    'kentext': '619f979bf2d4862c546a6aacc87f0ab2',
    'kogutext': '22c7d55a29d58e8487d8bd4468153b2a',
    'komutentext': '1da59a7df78a3d8271421777ffea0f3b',
    'kyoshujotext': '1620460de0a9555fe1520e29c3fe845b',
    'kyuhaisuitext': '009203f9ac51461ea99ca42af85c1502',
    'kyushokutext': 'f5d1136e296d34bbc3cd3120a58de550',
    'mokkotext': '5d18cece7bc9e41388228b1b6ec53d41',
    'nailtext': '86cf4cea65449fef20df99af2f26f3b2',
    'naisotext': '6aa6dd7df21257077c17fbb9335dc541',
    'nokitext': '08dfc9506b6a2c0c4f4fa81824259a53',
    'nougyotext': '15836709e686361f1cadc35f7c4f4a7b',
    'pettotext': '02e5e3cc3429e18a8711d795d91b0e90',
    'pharmtext': 'f1d9e878073c0a3b58e9a742cce1ac96',
    'phototext': '4b1890860f86b564a3ba40e66dcb5cec',
    'reizotext': '3988ea8916b237a8e819602994d22700',
    'rifotext': '4c9877204ce4fe761e56a2e72a171790',
    'ringyotext': '0473b4dbcfdc0db8dcae510387f8d630',
    'ryokantext': 'dc9c30e18e40a3f04e13b308b256d5f0',
    'salontext': '4539a0c44b41c09e1f02bd02fe91f20c',
    'sangyoitext': 'c575bb98ae17a30d009ccaba67bf3a6f',
    'seibitext': '28b38768b39555023ac219e435fe8fb2',
    'seishintext': 'c1acfc9e0abe22c88e9cab919b3bd813',
    'seisoutext': '0a97b5b54ac316fbcda4717451637848',
    'sekizaitext': '72aa1f15987cfeb7949402c15a85f69a',
    'sekkotsutext': '262a5e03879693de358ad0aa2881a706',
    'senmontext': '94c61b18eafcfe67e0aac08d8addbc32',
    'sharotext': '76696729ee88de81988fc9c067d7cd31',
    'shikatext': '14e3f26fab7375a17b86acd18d9d334d',
    'shindantext': '02d7f39f197ddbfbf6314d3be57d24bc',
    'shinkyutext': 'c7e5b50ba2eee7dc38b46d68f2d13de1',
    'shogyotext': '947f45123257797f12ff7cd0856c1075',
    'shokuhintext': '7cc2acb680dc990f3ac1a76daa59ad3d',
    'shoshitext': '8bdc13ea4a53217eb7948f835a352a9e',
    'shurotext': '70b1ffb9306b948c784b800cbcd2749c',
    'shushokutext': '6192661de7341430ef12a67d4c0e9491',
    'sogitext': '08238067144002dc2588b03a528f085c',
    'sokotext': 'a95bd6612a41815c719b074835ce80d3',
    'sokuryotext': 'e155ed802a701ab5cc493bb79d03b345',
    'sonpohokentext': '2784fb9e15d85a31e24be935263c7bff',
    'suisantext': 'ba05466cc3f4756f9fe2cf3aa84cd813',
    'supertext': '79c44966be396dd4c2bfe1ec3013ceba',
    'taxtext': 'b911e623f69de0f3d768e701bfa9576d',
    'tenjikaitext': '1dd288b83016e7f7efe338985211df4d',
    'tokutext': 'a8abc3a1049ca8e840cabf2c571b7730',
    'tokuyoutext': '3f5a2e5c91d693488cd84a491363f9fc',
    'tostext': 'f80ca062f4830888d2b90bb2e8610a4f',
    'unsotext': '21964d5bdbc6645b3d884f41f48ed9bd',
    'yakuhintext': '37e06989772ea04bdb1e73ac57abed13',
    'yakuzaishitext': '8ca6721a25cc3955e6bace0c9c95e3b7',
    'yanetext': '23295138c85360b92d147092a4d80c40',
    'yunyutext': '51b7ec0164443d0a0d24ce8668c818e3',
    'yurohokentext': '390bcd3ccfda5a33a291c0146abe38c7',
    'zoentext': '0a94992179d823482f5d337e45ced6a7',
}

def step1_save_gist_ids():
    """gist_ids.jsonを保存"""
    GIST_IDS_FILE.write_text(
        json.dumps(ALL_GIST_IDS, ensure_ascii=False, indent=2, sort_keys=True),
        encoding='utf-8'
    )
    print(f'[1] gist_ids.json 保存: {len(ALL_GIST_IDS)}件')

def step2_update_workflows():
    """全ワークフローのGIST_ID参照をgist_ids.jsonから読む形式に更新"""
    target_workflows = ['daily-send', 'check-replies', 'follow-up']
    updated = 0
    skipped = 0

    for wf_path in WORKFLOWS_DIR.glob('*.yml'):
        name = wf_path.stem
        # 対象ワークフロー判定
        slug = None
        for suffix in target_workflows:
            if name.endswith(f'-{suffix}'):
                slug = name[: -(len(suffix) + 1)]
                break
        if not slug:
            continue

        content = wf_path.read_text(encoding='utf-8')

        # 既に移行済みかチェック
        if 'gist_ids.json' in content:
            skipped += 1
            continue

        slug_upper = slug.upper()
        secret_ref = f'GIST_ID: ${{{{ secrets.{slug_upper}_SENT_LOG_GIST_ID }}}}'

        if secret_ref not in content:
            skipped += 1
            continue

        # パターン: env ブロックから GIST_ID 行を削除し、run ブロックの冒頭に追加
        # 1. env ブロックの GIST_ID 行を削除
        new_content = content.replace(
            f'          GIST_ID: ${{{{ secrets.{slug_upper}_SENT_LOG_GIST_ID }}}}\n',
            ''
        )

        # 2. curl 呼び出しの前に GIST_ID 抽出コマンドを追加
        # パターン: "run: |\n          curl -sf"
        old_run = '        run: |\n          curl -sf -H "Authorization: token $GIST_TOKEN" \\\n            "https://api.github.com/gists/$GIST_ID"'
        new_run = f'        run: |\n          GIST_ID=$(python3 -c "import json; print(json.load(open(\'shared/gtm/config/gist_ids.json\')).get(\'{slug}\',\'\'))")\n          curl -sf -H "Authorization: token $GIST_TOKEN" \\\n            "https://api.github.com/gists/$GIST_ID"'
        new_content = new_content.replace(old_run, new_run)

        # アップロード側の run パターンも更新
        old_upload_run = '        run: |\n          [ -f saas-dev/projects/{s}/outreach/sent_log.csv ] || exit 0'.format(s=slug)
        new_upload_run = '        run: |\n          GIST_ID=$(python3 -c "import json; print(json.load(open(\'shared/gtm/config/gist_ids.json\')).get(\'{s}\',\'\'))")\n          [ -f saas-dev/projects/{s}/outreach/sent_log.csv ] || exit 0'.format(s=slug)
        new_content = new_content.replace(old_upload_run, new_upload_run)

        if new_content != content:
            wf_path.write_text(new_content, encoding='utf-8')
            updated += 1
        else:
            skipped += 1

    print(f'[2] ワークフロー更新: {updated}件 / スキップ: {skipped}件')
    return updated

def step3_delete_old_secrets():
    """旧 *_SENT_LOG_GIST_ID シークレットを削除"""
    secrets_to_delete = [
        f'{slug.upper()}_SENT_LOG_GIST_ID' for slug in ALL_GIST_IDS
    ] + ['SENT_LOG_GIST_ID']  # 汎用シークレットも削除

    deleted = 0
    failed = []
    for secret in secrets_to_delete:
        result = subprocess.run(
            ['gh', 'secret', 'delete', secret, '--repo', 'ryuu321/ai-holdings'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f'  ✓ deleted {secret}')
            deleted += 1
        else:
            # 存在しないものはスキップ
            if 'not found' in result.stderr.lower() or 'could not find' in result.stderr.lower():
                pass
            else:
                failed.append(secret)
        time.sleep(0.1)

    print(f'[3] シークレット削除: {deleted}件 / 失敗: {len(failed)}件')
    if failed:
        print('  失敗:', failed)

if __name__ == '__main__':
    step1_save_gist_ids()
    updated = step2_update_workflows()
    if updated > 0:
        print(f'    ワークフロー {updated}件を更新しました')
    step3_delete_old_secrets()
    print('\n完了！ gist_ids.json に全103製品のGist IDを保存し、シークレットを整理しました。')
