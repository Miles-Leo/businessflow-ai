# 模块职责：显式评测入口；真实模型轨道会消耗额度，结果不能替代人工语义复核。
import argparse
import json
from pathlib import Path
from app.ai.evaluation import evaluate_rules, evaluate_live_agent, save_report
from app.ai.fixed_evaluation import evaluate_fixed_agent, evaluate_retrieval, provenance, write_markdown


def main():
    parser = argparse.ArgumentParser(description="固定评测；默认离线规则，--live/--retrieval/--integration 会消耗外部额度")
    parser.add_argument("--live", action="store_true", help="真实Qwen + 固定虚构工具结果（15例）")
    parser.add_argument("--retrieval", action="store_true", help="真实Embedding/Milvus条款覆盖（4例）")
    parser.add_argument("--integration", action="store_true", help="旧版5例真实只读全链路冒烟，依赖当前数据库")
    parser.add_argument("--repeat", type=int, default=1, choices=range(1, 6), help="固定模型评测重复次数1到5")
    parser.add_argument("--output", type=Path, default=Path("reports"))
    args = parser.parse_args()
    report = {"provenance": provenance(), "rules": evaluate_rules()}
    if args.live:
        report["agent"] = evaluate_fixed_agent(args.repeat)
    if args.retrieval:
        report["retrieval"] = evaluate_retrieval()
    if args.integration:
        report["integration"] = evaluate_live_agent()
    path = save_report(report, args.output)
    write_markdown(report, path)
    print(json.dumps({"report": str(path), **{key: {k: v for k, v in report[key].items() if k != "cases"}
                                            for key in ["rules", "agent", "retrieval", "integration"] if key in report}}, ensure_ascii=False))
    failed = report["rules"]["current_passed"] != report["rules"]["total"]
    failed |= any(report[key]["passed"] != report[key]["total"] for key in ["agent", "retrieval", "integration"] if key in report)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
