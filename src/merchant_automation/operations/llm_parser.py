"""LLM-based intelligent parser for natural language instructions.

Uses LLM to understand user intent and map to operations, providing
better generalization than regex-based parsing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from merchant_automation.operations.catalog import OperationCatalog
from merchant_automation.operations.schemas import ExecutionMode, OperationTask

logger = logging.getLogger(__name__)

# System prompt for LLM parser
PARSE_SYSTEM_PROMPT = """你是一个外卖商家后台操作解析器。你的任务是将用户的自然语言指令解析为结构化的操作。

## 支持的操作

{operations}

## 输出格式

请返回JSON格式：
```json
{{
  "operation_id": "操作ID",
  "platform": "平台(meituan/eleme/douyin)",
  "store": "店铺名称",
  "params": {{
    "参数名": "参数值"
  }},
  "confidence": 0.95
}}
```

## 解析规则

1. **平台识别**：美团/美团外卖 → meituan，饿了么 → eleme，抖音/抖音来客 → douyin
2. **店铺提取**：提取平台后面的店铺名称
3. **参数提取**：根据操作类型提取必要参数
4. **模糊匹配**：支持口语化表达，如"改个电话"→"修改电话"
5. **数字识别**：自动识别电话、价格、数量等数字

## 示例

用户："把美团 江湖饭焗 电话改成 13800138000"
```json
{{
  "operation_id": "update_store_phone",
  "platform": "meituan",
  "store": "江湖饭焗",
  "params": {{"phone": "13800138000"}},
  "confidence": 0.98
}}
```

用户："江湖饭焗的配送费改成5块"
```json
{{
  "operation_id": "update_delivery_fee",
  "platform": "meituan",
  "store": "江湖饭焗",
  "params": {{"delivery_fee": "5"}},
  "confidence": 0.90
}}
```

如果无法识别，返回：
```json
{{
  "operation_id": null,
  "error": "无法识别的操作",
  "confidence": 0.0
}}
```"""


class LLMParseError(Exception):
    """Raised when LLM parsing fails."""


class LLMParser:
    """LLM-based intelligent parser for natural language instructions."""

    def __init__(self, llm=None) -> None:
        self._llm = llm
        self._catalog = OperationCatalog.default()

    def _get_operations_description(self) -> str:
        """Generate operations description for system prompt."""
        lines = []
        for op_id, op in self._catalog.operations.items():
            params = ", ".join(op.required_params) if op.required_params else "无"
            lines.append(f"- **{op_id}** ({op.title}): 参数=[{params}]")
        return "\n".join(lines)

    def _build_system_prompt(self) -> str:
        """Build system prompt with operations info."""
        return PARSE_SYSTEM_PROMPT.format(
            operations=self._get_operations_description()
        )

    async def parse(self, text: str, *, mode: ExecutionMode = ExecutionMode.PARSE_ONLY) -> OperationTask:
        """Parse natural language instruction using LLM."""
        if self._llm is None:
            raise LLMParseError("LLM not configured")

        from browser_use.llm.messages import UserMessage, SystemMessage

        system_prompt = self._build_system_prompt()
        user_prompt = f"请解析以下指令：\n\n{text}"

        try:
            response = await self._llm.ainvoke([
                SystemMessage(content=system_prompt),
                UserMessage(content=user_prompt),
            ])

            # Extract JSON from response
            result = self._extract_json(response.completion)

            # Validate response
            if not result.get("operation_id"):
                raise LLMParseError(f"无法识别的操作: {result.get('error', '未知错误')}")

            # Build OperationTask
            return OperationTask(
                platform=result.get("platform", "meituan"),
                store_id=result.get("store", ""),
                operation_id=result["operation_id"],
                params=result.get("params", {}),
                mode=mode,
            )

        except Exception as e:
            if isinstance(e, LLMParseError):
                raise
            raise LLMParseError(f"LLM解析失败: {str(e)}")

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Extract JSON from LLM response."""
        import re

        # Try to find JSON in code blocks
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        # Try to find JSON directly (handle nested objects)
        start = text.find('{')
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[start:i+1])

        raise LLMParseError("无法从LLM响应中提取JSON")


class HybridParser:
    """Hybrid parser combining regex and LLM parsing.

    Tries regex first (fast), falls back to LLM (flexible).
    """

    def __init__(self, llm=None) -> None:
        from merchant_automation.operations.parser import OperationParser
        self._regex_parser = OperationParser()
        self._llm_parser = LLMParser(llm) if llm else None

    async def parse(self, text: str, *, mode: ExecutionMode = ExecutionMode.PARSE_ONLY) -> OperationTask:
        """Parse instruction using regex first, then LLM if needed."""
        # Try regex parser first (fast, deterministic)
        try:
            return self._regex_parser.parse_text(text, mode=mode)
        except Exception as regex_error:
            logger.debug("Regex parsing failed: %s", regex_error)

            # Fall back to LLM parser if available
            if self._llm_parser:
                try:
                    return await self._llm_parser.parse(text, mode=mode)
                except Exception as llm_error:
                    logger.warning("LLM parsing also failed: %s", llm_error)
                    raise llm_error

            raise regex_error
