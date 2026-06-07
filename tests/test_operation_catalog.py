from merchant_automation.operations.catalog import OperationCatalog


def test_catalog_contains_first_batch_operations():
	catalog = OperationCatalog.default()

	assert catalog.get('update_store_phone').title == '修改门店联系电话'
	assert catalog.get('change_business_hours').allow_commit is True
	assert catalog.get('replace_product_image').allow_commit is False
	assert catalog.get('update_store_decoration_image').allow_commit is False


def test_catalog_rejects_unknown_operation():
	catalog = OperationCatalog.default()

	try:
		catalog.get('change_product_price')
	except KeyError as exc:
		assert 'Unsupported operation' in str(exc)
	else:
		raise AssertionError('expected KeyError')
