from pathlib import Path


def test_server_does_not_import_legacy_feishu_browser_use_package():
	server_source = Path('src/merchant_automation/server.py').read_text(encoding='utf-8')

	assert 'feishu_browser_use' not in server_source
