"""Recipe definitions for common operations.

All recipes navigate to the merchant homepage first, then click through
to the target page. Deep-linking to sub-pages causes 404 redirects because
the merchant backend is a SPA that requires session establishment on the
home page before navigating to sub-routes.
"""

from collections.abc import Mapping

from merchant_automation.operations.recipe_definition import RecipeDefinition, RecipeStep, RecipeStepAction

# 美团商家后台首页 — 所有操作从这里开始
MEITUAN_HOME = 'https://e.waimai.meituan.com/'

RECIPE_DEFINITIONS: dict[str, RecipeDefinition] = {
    'meituan.update_store_phone.v1': RecipeDefinition(
        recipe_id='meituan.update_store_phone.v1',
        entry_url=MEITUAN_HOME,
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url=MEITUAN_HOME,
                description='打开美团商家后台首页',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待首页加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店设置或门店信息菜单',
                description='进入门店信息页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待门店信息页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='电话号码或联系电话编辑按钮',
                description='点击电话号码区域进入编辑状态',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=2,
                description='等待编辑框出现',
            ),
            RecipeStep(
                action=RecipeStepAction.FILL,
                target='电话号码输入框',
                value='{phone}',
                description='填入新电话号码',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=1,
                description='等待输入完成',
            ),
            RecipeStep(
                action=RecipeStepAction.SCREENSHOT,
                description='保存前截图',
            ),
            RecipeStep(
                action=RecipeStepAction.STOP_BEFORE_SUBMIT,
                description='停在保存前',
            ),
        ],
        verify_after_commit=['保存成功', '修改成功', '操作成功'],
    ),

    'meituan.change_business_hours.v1': RecipeDefinition(
        recipe_id='meituan.change_business_hours.v1',
        entry_url=MEITUAN_HOME,
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url=MEITUAN_HOME,
                description='打开美团商家后台首页',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待首页加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店设置或门店信息菜单',
                description='进入门店信息页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待门店信息页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='营业时间编辑按钮',
                description='点击营业时间区域',
            ),
            RecipeStep(
                action=RecipeStepAction.FILL,
                target='开始时间输入框',
                value='{start_time}',
                description='填入开始时间',
            ),
            RecipeStep(
                action=RecipeStepAction.FILL,
                target='结束时间输入框',
                value='{end_time}',
                description='填入结束时间',
            ),
            RecipeStep(
                action=RecipeStepAction.SCREENSHOT,
                description='保存前截图',
            ),
            RecipeStep(
                action=RecipeStepAction.STOP_BEFORE_SUBMIT,
                description='停在保存前',
            ),
        ],
        verify_after_commit=['保存成功', '修改成功'],
    ),

    'meituan.update_store_name.v1': RecipeDefinition(
        recipe_id='meituan.update_store_name.v1',
        entry_url=MEITUAN_HOME,
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url=MEITUAN_HOME,
                description='打开美团商家后台首页',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待首页加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店设置或门店信息菜单',
                description='进入门店信息页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待门店信息页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店名称编辑按钮',
                description='点击门店名称区域',
            ),
            RecipeStep(
                action=RecipeStepAction.FILL,
                target='门店名称输入框',
                value='{store_name}',
                description='填入新门店名称',
            ),
            RecipeStep(
                action=RecipeStepAction.SCREENSHOT,
                description='保存前截图',
            ),
            RecipeStep(
                action=RecipeStepAction.STOP_BEFORE_SUBMIT,
                description='停在保存前',
            ),
        ],
        verify_after_commit=['保存成功', '修改成功'],
    ),

    'meituan.update_store_decoration_image.v1': RecipeDefinition(
        recipe_id='meituan.update_store_decoration_image.v1',
        entry_url=MEITUAN_HOME,
        page_variant='2026-06',
        verified_at='2026-06-08',
        verified_account_id='system',
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url=MEITUAN_HOME,
                description='打开美团商家后台首页',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待首页加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店设置或门店装修菜单',
                description='进入门店装修页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待门店装修页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店照片或门店图片编辑入口',
                description='进入门店照片编辑',
            ),
            RecipeStep(
                action=RecipeStepAction.UPLOAD,
                target='图片上传输入框',
                value='{local_image_path}',
                description='上传本地图片',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待图片上传完成',
            ),
            RecipeStep(
                action=RecipeStepAction.SCREENSHOT,
                description='保存前截图',
            ),
            RecipeStep(
                action=RecipeStepAction.STOP_BEFORE_SUBMIT,
                description='停在保存前',
            ),
        ],
        verify_after_commit=['保存成功', '修改成功', '上传成功'],
    ),
}


def builtin_recipe_definitions() -> dict[str, RecipeDefinition]:
    """Return fresh copies of built-in deterministic definitions."""
    return {
        recipe_id: definition.model_copy(deep=True)
        for recipe_id, definition in RECIPE_DEFINITIONS.items()
    }


def merge_recipe_definitions(
    persisted_definitions: Mapping[str, RecipeDefinition] | None,
) -> dict[str, RecipeDefinition]:
    """Merge persisted definitions over built-in defaults.

    Persisted definitions win so manual edits and auto-synthesized recipes are never hidden by
    the code defaults.
    """
    merged = builtin_recipe_definitions()
    if persisted_definitions:
        merged.update(persisted_definitions)
    return merged
