"""Recipe definitions for common operations."""

from collections.abc import Mapping

from merchant_automation.operations.recipe_definition import RecipeDefinition, RecipeStep, RecipeStepAction

# Correct entry URL for Meituan merchant backend
MEITUAN_ENTRY_URL = 'https://e.waimai.meituan.com/'

RECIPE_DEFINITIONS: dict[str, RecipeDefinition] = {
    'meituan.update_store_phone.v1': RecipeDefinition(
        recipe_id='meituan.update_store_phone.v1',
        entry_url=MEITUAN_ENTRY_URL,
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url=MEITUAN_ENTRY_URL,
                description='导航到美团外卖商家后台首页',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='店铺设置菜单',
                description='展开店铺设置菜单',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=1,
                description='等待菜单展开',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店管理子菜单',
                description='进入门店管理页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待门店管理页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='修改按钮',
                description='点击修改按钮进入编辑状态',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=2,
                description='等待编辑状态',
            ),
            RecipeStep(
                action=RecipeStepAction.FILL,
                target='餐厅电话输入框',
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
        entry_url=MEITUAN_ENTRY_URL,
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url=MEITUAN_ENTRY_URL,
                description='导航到美团外卖商家后台首页',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='店铺设置菜单',
                description='展开店铺设置菜单',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=1,
                description='等待菜单展开',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店管理子菜单',
                description='进入门店管理页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待门店管理页面加载',
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
        entry_url=MEITUAN_ENTRY_URL,
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url=MEITUAN_ENTRY_URL,
                description='导航到美团外卖商家后台首页',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='店铺设置菜单',
                description='展开店铺设置菜单',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=1,
                description='等待菜单展开',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店管理子菜单',
                description='进入门店管理页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待门店管理页面加载',
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
        entry_url=MEITUAN_ENTRY_URL,
        page_variant='2026-06',
        verified_at='2026-06-08',
        verified_account_id='system',
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url=MEITUAN_ENTRY_URL,
                description='导航到美团外卖商家后台首页',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='店铺设置菜单',
                description='展开店铺设置菜单',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=1,
                description='等待菜单展开',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='门店装修子菜单',
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
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='保存按钮',
                description='保存门店照片',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待保存完成',
            ),
            RecipeStep(
                action=RecipeStepAction.VERIFY,
                target='页面提示',
                description='验证是否显示保存成功',
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
