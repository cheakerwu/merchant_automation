"""Login service — handles browser-based login flow for merchant platforms."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from merchant_automation.accounts.manager import AccountManager
from merchant_automation.accounts.models import Account, AccountStatus, LoginStatus
from merchant_automation.accounts.store import AccountStore
from merchant_automation.config import Settings
from merchant_automation.feishu.bot import FeishuBot

logger = logging.getLogger(__name__)

LOGIN_WAIT_TIMEOUT_SECONDS = 15 * 60
LOGIN_CHECK_POLL_SECONDS = 3
LOGIN_PAGE_TEXT_LIMIT = 3000
LOGIN_BROWSER_START_TIMEOUT_SECONDS = 60

LOGIN_DETECTION_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    'meituan': {
        'success_url': ('e.waimai.meituan.com',),
        'success_title': ('美团外卖商家中心',),
        'success_text': ('订单管理', '商品管理', '门店', '工作台'),
        'login_url': ('passport.meituan.com',),
    },
    'eleme': {
        'success_url': ('ele.me',),
        'success_title': ('饿了么商家中心',),
        'success_text': ('订单管理', '商品管理', '门店'),
        'login_url': ('passport.ele.me',),
    },
    'douyin': {
        'success_url': ('fxg.jinritemai.com',),
        'success_title': ('抖音来客',),
        'success_text': ('订单管理', '商品管理', '门店'),
        'login_url': ('sso.jinritemai.com',),
    },
}


class LoginService:
    """Handles browser-based login flow for merchant platforms."""

    def __init__(
        self,
        config: Settings,
        account_manager: AccountManager,
        account_store: AccountStore,
        feishu_bot: FeishuBot,
    ) -> None:
        self._config = config
        self._account_manager = account_manager
        self._account_store = account_store
        self._feishu_bot = feishu_bot

    async def start_login(self, platform: str, store_name: str, chat_id: str) -> Account:
        """Create or reuse account and start headful login flow."""
        # Search for existing account
        accounts = await self._account_manager.search_accounts(store_name)
        account = next((a for a in accounts if a.platform == platform), None)

        if account is None:
            # Create new account
            account = await self._account_manager.create_account(store_name, platform)
            await self._sync_account_store(account, AccountStatus.NEEDS_LOGIN)
        else:
            # Mark existing account as needs login
            await self._update_login_account_status(account, AccountStatus.NEEDS_LOGIN)

        return account

    async def execute_login_flow(self, account_id: str, chat_id: str) -> None:
        """Execute the headful login flow for an account."""
        account = await self._account_manager.get_account(account_id)
        if account is None:
            await self._feishu_bot.send_text(chat_id, f'找不到账号 {account_id}')
            return

        platform = account.platform
        platform_display = platform.capitalize()
        await self._feishu_bot.send_text(
            chat_id,
            f'正在打开浏览器登录 {platform_display}/{account.name}\n'
            f'请在浏览器中完成登录，系统会自动检测登录状态。',
        )

        try:
            from browser_use import BrowserSession
            from browser_use.browser.profile import BrowserProfile

            # Create headful browser session
            profile = BrowserProfile(
                headless=False,
                enable_default_extensions=False,
                user_data_dir=account.profile_dir,
            )
            browser_session = BrowserSession(browser_profile=profile)

            try:
                await browser_session.start()

                # Navigate to login page
                login_url = self._login_url_for_platform(platform)
                await browser_session.navigate_to(login_url)

                # Wait for login success
                success = await self._wait_for_login_success(browser_session, platform, chat_id)

                if success:
                    await self._update_login_account_status(account, AccountStatus.ACTIVE)
                    await self._sync_account_store(account, AccountStatus.ACTIVE)
                    await self._feishu_bot.send_text(
                        chat_id,
                        f'{account.name} 登录成功，登录态已保存。',
                    )
                else:
                    await self._update_login_account_status(account, AccountStatus.NEEDS_LOGIN)
                    await self._sync_account_store(account, LoginStatus.EXPIRED)
                    await self._feishu_bot.send_text(
                        chat_id,
                        f'暂未检测到登录成功，请重新发送"登录 {platform} {account.name}"重试。',
                    )

            finally:
                try:
                    await browser_session.close()
                except Exception:
                    pass

        except Exception as exc:
            logger.exception('Login flow failed for account %s', account_id)
            await self._feishu_bot.send_text(
                chat_id,
                f'登录过程出现异常：{str(exc)[:100]}',
            )

    async def _wait_for_login_success(
        self,
        browser_session: Any,
        platform: str,
        chat_id: str,
    ) -> bool:
        """Wait for login success by polling page URL and content."""
        rules = LOGIN_DETECTION_RULES.get(platform, {})
        success_urls = rules.get('success_url', ())
        success_titles = rules.get('success_title', ())
        success_texts = rules.get('success_text', ())

        elapsed = 0.0
        while elapsed < LOGIN_WAIT_TIMEOUT_SECONDS:
            try:
                url = await browser_session.get_current_page_url()
                title = await browser_session.get_current_page_title()

                # Check URL
                if any(su in url for su in success_urls):
                    return True

                # Check title
                if any(st in title for st in success_titles):
                    return True

                # Check page text
                try:
                    page = await browser_session.get_current_page()
                    if page:
                        text = await page.evaluate('(...args) => document.body.innerText')
                        text = text[:LOGIN_PAGE_TEXT_LIMIT]
                        if any(st in text for st in success_texts):
                            return True
                except Exception:
                    pass

            except Exception:
                logger.warning('Error checking login status', exc_info=True)

            await asyncio.sleep(LOGIN_CHECK_POLL_SECONDS)
            elapsed += LOGIN_CHECK_POLL_SECONDS

        return False

    def _login_url_for_platform(self, platform: str) -> str:
        """Get the login URL for a platform."""
        urls = {
            'meituan': 'https://e.waimai.meituan.com/',
            'eleme': 'https://www.ele.me/',
            'douyin': 'https://fxg.jinritemai.com/',
        }
        return urls.get(platform, urls['meituan'])

    async def _update_login_account_status(self, account: Account, status: AccountStatus) -> None:
        """Update account status and sync to account store."""
        await self._account_manager.update_status(account.id, status)
        refreshed = await self._account_manager.get_account(account.id)
        self._sync_account_store(refreshed or account, status)

    def _sync_account_store(self, account: Account, status: AccountStatus) -> None:
        """Sync account to account store for dashboard display."""
        login_status = LoginStatus.LOGGED_IN if status == AccountStatus.ACTIVE else LoginStatus.EXPIRED
        platform_account = PlatformAccount(
            account_id=account.id,
            platform=account.platform,
            username=account.name,
            profile_path=account.profile_dir,
            login_status=login_status,
        )
        self._account_store.upsert_account(platform_account)
