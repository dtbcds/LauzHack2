"""Validate dependency examples, fine-tune Qwen3 with QLoRA, and export for Ollama."""

import argparse
import json
from pathlib import Path

from dependency_extraction import build_user_message


BASE_MODEL = "Qwen/Qwen3-8B"
WEIGHTS = {"hard": 1.0, "soft": 0.5}


def load_examples(path: Path) -> list[dict]:
    if not path.is_file():
        raise ValueError(f"Dataset not found: {path}")
    examples = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            target = row["target_task"]
            candidates = row["candidate_tasks"]
            dependencies = row["dependencies"]
            target_id = target["id"]
            candidate_ids = [task["id"] for task in candidates]
            if (
                not isinstance(target_id, str) or not target_id
                or not isinstance(target.get("description"), str)
                or not isinstance(candidates, list)
                or not isinstance(dependencies, list)
                or any(not isinstance(task, dict) or not isinstance(task.get("id"), str)
                       or not task["id"] or not isinstance(task.get("description"), str)
                       for task in candidates)
                or len(candidate_ids) != len(set(candidate_ids))
                or target_id in candidate_ids
            ):
                raise ValueError("invalid task or candidate list")
            seen = set()
            for dep in dependencies:
                candidate_id = dep["prerequisite_task_id"]
                candidate = next((task for task in candidates if task["id"] == candidate_id), None)
                kind = dep["type"]
                evidence = dep["evidence"]
                confidence = dep["confidence"]
                if (
                    candidate is None or candidate_id in seen
                    or dep["dependent_task_id"] != target_id
                    or kind not in WEIGHTS or isinstance(dep["weight"], bool)
                    or dep["weight"] != WEIGHTS[kind]
                    or not isinstance(evidence, str) or not evidence
                    or evidence not in target["description"]
                    and evidence not in candidate["description"]
                    or isinstance(confidence, bool)
                    or not isinstance(confidence, (int, float))
                    or not 0 <= confidence <= 1
                ):
                    raise ValueError("invalid dependency label")
                seen.add(candidate_id)
            examples.append({
                "messages": [
                    {"role": "user", "content": build_user_message(target, candidates)},
                    {"role": "assistant", "content": json.dumps(
                        {"target_task_id": target_id, "dependencies": dependencies},
                        ensure_ascii=False,
                    )},
                ]
            })
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    if not examples:
        raise ValueError(f"Dataset is empty: {path}")
    return examples


def train(args: argparse.Namespace) -> None:
    import importlib.util
    import torch
    from datasets import Dataset
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    if not torch.cuda.is_available():
        raise RuntimeError("QLoRA training requires a CUDA GPU")
    if args.packing and importlib.util.find_spec("flash_attn") is None:
        raise RuntimeError("--packing requires flash-attn")
    training = load_examples(args.train)
    validation = load_examples(args.validation) if args.validation else None
    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    tokenizer.pad_token = tokenizer.eos_token
    for split, rows in (("train", training), ("validation", validation or [])):
        for index, row in enumerate(rows, 1):
            tokens = tokenizer.apply_chat_template(row["messages"], tokenize=True)
            token_count = len(tokens["input_ids"] if isinstance(tokens, dict) else tokens)
            if token_count > args.max_length:
                raise ValueError(
                    f"{split} example {index} has {token_count} tokens; "
                    f"increase --max-length or shorten the example"
                )
    compute_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        device_map="auto",
        torch_dtype=compute_dtype,
        **({"attn_implementation": "flash_attention_2"} if args.packing else {}),
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=compute_dtype,
        ),
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model)
    config = SFTConfig(
        output_dir=str(args.output),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        max_length=args.max_length,
        assistant_only_loss=True,
        packing=args.packing,
        packing_strategy="bfd",
        eval_packing=False,
        optim="adamw_torch_fused",
        bf16=compute_dtype == torch.bfloat16,
        fp16=compute_dtype == torch.float16,
        eval_strategy="epoch" if validation else "no",
        save_strategy="epoch",
        save_total_limit=2,
        report_to="none",
        seed=args.seed,
    )
    trainer = SFTTrainer(
        model=model,
        args=config,
        train_dataset=Dataset.from_list(training),
        eval_dataset=Dataset.from_list(validation) if validation else None,
        processing_class=tokenizer,
        peft_config=LoraConfig(
            r=16, lora_alpha=32, lora_dropout=0.05,
            target_modules="all-linear", task_type="CAUSAL_LM",
        ),
    )
    trainer.train(
        resume_from_checkpoint=str(args.resume_from_checkpoint)
        if args.resume_from_checkpoint else None
    )
    trainer.save_model(str(args.output / "adapter"))
    tokenizer.save_pretrained(str(args.output / "adapter"))


def export(args: argparse.Namespace) -> None:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    adapter_config = json.loads((args.adapter / "adapter_config.json").read_text())
    base_model = adapter_config["base_model_name_or_path"]
    model = AutoModelForCausalLM.from_pretrained(
        base_model, torch_dtype=torch.float16, device_map="cpu", low_cpu_mem_usage=True,
    )
    merged = PeftModel.from_pretrained(model, args.adapter).merge_and_unload()
    args.output.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(args.output, safe_serialization=True, max_shard_size="4GB")
    AutoTokenizer.from_pretrained(base_model).save_pretrained(args.output)
    (args.output / "Modelfile").write_text("FROM .\n", encoding="utf-8")


def evaluate(args: argparse.Namespace) -> None:
    import dependency_extraction

    dependency_extraction.MODEL = args.model
    rows = [json.loads(line) for line in args.data.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    load_examples(args.data)
    correct = total = 0
    confusion = {gold: {pred: 0 for pred in ("hard", "soft", "none")}
                 for gold in ("hard", "soft", "none")}
    for row in rows:
        result = dependency_extraction.extract_dependencies(
            row["target_task"], row["candidate_tasks"]
        )
        gold = {dep["prerequisite_task_id"]: dep["type"]
                for dep in row["dependencies"]}
        predicted = {dep["prerequisite_task_id"]: dep["type"]
                     for dep in result["dependencies"]}
        correct += gold == predicted
        total += 1
        for candidate in row["candidate_tasks"]:
            task_id = candidate["id"]
            confusion[gold.get(task_id, "none")][predicted.get(task_id, "none")] += 1
    print(json.dumps({"exact_match": correct / total, "examples": total,
                      "confusion": confusion}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate")
    validate.add_argument("paths", type=Path, nargs="+")
    fit = subcommands.add_parser("train")
    fit.add_argument("--train", type=Path, required=True)
    fit.add_argument("--validation", type=Path)
    fit.add_argument("--output", type=Path, required=True)
    fit.add_argument("--base-model", default=BASE_MODEL)
    fit.add_argument("--epochs", type=float, default=2)
    fit.add_argument("--learning-rate", type=float, default=2e-4)
    fit.add_argument("--gradient-accumulation", type=int, default=8)
    fit.add_argument("--batch-size", type=int, default=1)
    fit.add_argument("--packing", action="store_true")
    fit.add_argument("--max-length", type=int, default=1024)
    fit.add_argument("--seed", type=int, default=42)
    fit.add_argument("--resume-from-checkpoint", type=Path)
    merge = subcommands.add_parser("export")
    merge.add_argument("--adapter", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    assessment = subcommands.add_parser("evaluate")
    assessment.add_argument("--data", type=Path, required=True)
    assessment.add_argument("--model", default="dependency-qwen3-v2:q4")
    args = parser.parse_args()
    if args.command == "validate":
        for path in args.paths:
            print(f"{path}: {len(load_examples(path))} valid examples")
    elif args.command == "train":
        train(args)
    elif args.command == "evaluate":
        evaluate(args)
    else:
        export(args)


if __name__ == "__main__":
    main()
