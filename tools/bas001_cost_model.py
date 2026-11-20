"""BAS-001: 逐笔配对套利净收益核算（标准库，无外部依赖）。

输入 JSON（示例见 config/bas001_cost_example.json）：所有成交价格必须是实际成交价，
或明确标记为模拟价格；不使用中间价假装成交价。
注意：当成交价已经包含 Bid/Ask 时，不能再减一次买卖价差。
Funding 为带符号的实际现金流（收取为正）；financing_usd 为非负融资成本。
"""
import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path


def dec(value, name):
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} 必须是有限数字") from None


def calculate(record):
    """以 USD 计价、双腿单位数量相同的线性合约；不适用于未经转换的反向合约。"""
    qty = dec(record["quantity"], "quantity")
    if qty <= 0:
        raise ValueError("quantity 必须大于 0")
    prices = {k: dec(record[k], k) for k in (
        "spot_open_ask", "spot_close_bid", "perp_open_bid", "perp_close_ask"
    )}
    if any(v <= 0 for v in prices.values()):
        raise ValueError("成交价必须大于 0")
    spot_gross = qty * (prices["spot_close_bid"] - prices["spot_open_ask"])
    perp_gross = qty * (prices["perp_open_bid"] - prices["perp_close_ask"])
    gross = spot_gross + perp_gross

    platform_fees = dec(record.get("platform_commission_usd", 0), "platform_commission_usd")
    if platform_fees < 0:
        raise ValueError("平台已扣手续费不能为负")
    rates = record.get("commission_rates", {})
    if platform_fees and any(dec(rates.get(k, 0), k) for k in (
        "spot_open", "spot_close", "perp_open", "perp_close"
    )):
        raise ValueError("平台已有手续费记录时不可再次用费率重复扣费")
    legs = {
        "spot_open": qty * prices["spot_open_ask"],
        "spot_close": qty * prices["spot_close_bid"],
        "perp_open": qty * prices["perp_open_bid"],
        "perp_close": qty * prices["perp_close_ask"],
    }
    calc_fees = sum(notional * dec(rates.get(k, 0), "fee rate")
                    for k, notional in legs.items())
    if any(dec(v, "fee rate") < 0 for v in rates.values()):
        raise ValueError("费率不得为负")
    commission = platform_fees or calc_fees

    extra_slippage = dec(record.get("extra_slippage_usd", 0), "extra_slippage_usd")
    funding = dec(record.get("net_funding_usd", 0), "net_funding_usd")
    financing = dec(record.get("financing_usd", 0), "financing_usd")
    if extra_slippage < 0 or financing < 0:
        raise ValueError("滑点损失/融资成本应为非负值")
    net = gross - commission - extra_slippage + funding - financing
    return {
        "spot_gross_pnl_usd": str(spot_gross),
        "perp_gross_pnl_usd": str(perp_gross),
        "gross_pnl_usd": str(gross),
        "commission_usd": str(commission),
        "extra_slippage_usd": str(extra_slippage),
        "net_funding_usd": str(funding),
        "financing_usd": str(financing),
        "net_pnl_usd": str(net)
    }


def main():
    parser = argparse.ArgumentParser(description="BAS-001 单笔配对套利净收益核算")
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input_json.read_text(encoding="utf-8"))
    result = calculate(payload)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
