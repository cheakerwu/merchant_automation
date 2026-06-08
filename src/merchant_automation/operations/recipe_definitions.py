"""Recipe definitions for common operations."""

from collections.abc import Mapping

from merchant_automation.operations.recipe_definition import RecipeDefinition, RecipeStep, RecipeStepAction

RECIPE_DEFINITIONS: dict[str, RecipeDefinition] = {
    'meituan.update_store_phone.v1': RecipeDefinition(
        recipe_id='meituan.update_store_phone.v1',
        entry_url='https://e.waimai.meituan.com/new_fe/shop/account/info',
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url='https://e.waimai.meituan.com/new_fe/shop/account/info',
                description='导航到门店信息页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待页面加载',
            ),
            RecipeStep(
                action=RecipeStepAction.CLICK,
                target='电话号码输入框或编辑按钮',
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
        entry_url='https://e.waimai.meituan.com/new_fe/shop/account/info',
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url='https://e.waimai.meituan.com/new_fe/shop/account/info',
                description='导航到门店信息页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待页面加载',
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
        entry_url='https://e.waimai.meituan.com/new_fe/shop/account/info',
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url='https://e.waimai.meituan.com/new_fe/shop/account/info',
                description='导航到门店信息页面',
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
        entry_url='https://e.waimai.meituan.com/new_fe/shop/decorate',
        steps=[
            RecipeStep(
                action=RecipeStepAction.NAVIGATE,
                url='https://e.waimai.meituan.com/new_fe/shop/decorate',
                description='导航到门店装修页面',
            ),
            RecipeStep(
                action=RecipeStepAction.WAIT,
                timeout=3,
                description='等待页面加载',
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
