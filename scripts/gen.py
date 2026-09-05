#!/usr/bin/env python3
"""
gen.py — единый CLI к агрегаторам моделей: kie.ai, fal.ai, wavespeed.ai.

Отправляет задачу, ждёт результат, скачивает файлы, пишет строку в лог.
Ключи берутся из окружения: KIE_API_KEY, FAL_KEY, WAVESPEED_API_KEY.

Примеры:
  gen.py run --provider kie --model google/nano-banana \
      --input '{"prompt":"a red fox in snow","aspect_ratio":"1:1"}' --cost 0.02

  gen.py run --provider fal --model fal-ai/flux/dev \
      --input '{"prompt":"ceramic vase, soft light","image_size":"portrait_4_3"}' --cost 0.025

  gen.py balance --provider fal
  gen.py spent --since today
  gen.py log --last 10

Зависимости: только стандартная библиотека.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path(os.environ.get("GENERATE_OUT_DIR", "generations"))
LOG_PATH = OUT_DIR / "log.jsonl"
POLL_START = 2.0
POLL_MAX = 10.0


# ---------------------------------------------------------------- http

def _req(method, url, key_header=None, body=None, headers=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if key_header:
        h["Authorization"] = key_header
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw": raw}


def _key(env_name):
    v = os.environ.get(env_name)
    if not v:
        die(f"нет ключа: переменная окружения {env_name} не установлена")
    return v


def die(msg, code=2):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------- providers
#
# Каждый провайдер: submit() -> task_id, poll() -> (state, urls, error), balance().
# state: "pending" | "done" | "failed"

class Fal:
    name = "fal"
    env = "FAL_KEY"

    def auth(self):
        return f"Key {_key(self.env)}"

    def submit(self, model, payload):
        st, r = _req("POST", f"https://queue.fal.run/{model}", self.auth(), payload)
        if st >= 400 or "request_id" not in r:
            die(f"fal submit {st}: {json.dumps(r, ensure_ascii=False)[:600]}")
        return r["request_id"]

    def poll(self, model, task_id):
        # Очередь fal живёт на уровне приложения (owner/app), а не эндпоинта:
        # submit шлём на полный путь (fal-ai/nano-banana/edit), но status и
        # результат — только по первым двум сегментам (fal-ai/nano-banana),
        # иначе 405. Подтверждено на fal-ai/nano-banana/edit.
        app = "/".join(model.split("/")[:2])
        st, r = _req("GET", f"https://queue.fal.run/{app}/requests/{task_id}/status", self.auth())
        if st >= 400:
            return "failed", [], f"status {st}: {r}"
        s = r.get("status")
        if s in ("IN_QUEUE", "IN_PROGRESS"):
            return "pending", [], None
        # COMPLETED означает "закончено", не обязательно "успешно"
        st2, res = _req("GET", f"https://queue.fal.run/{app}/requests/{task_id}", self.auth())
        if st2 >= 400 or res.get("detail"):
            return "failed", [], json.dumps(res, ensure_ascii=False)[:600]
        return "done", _harvest_urls(res), None

    def balance(self):
        return None, "fal не отдаёт баланс по публичному API — смотри дашборд fal.ai"


class Kie:
    name = "kie"
    env = "KIE_API_KEY"

    def auth(self):
        return f"Bearer {_key(self.env)}"

    def submit(self, model, payload):
        st, r = _req("POST", "https://api.kie.ai/api/v1/jobs/createTask",
                     self.auth(), {"model": model, "input": payload})
        if st >= 400 or r.get("code") != 200:
            die(f"kie submit {st}: {json.dumps(r, ensure_ascii=False)[:600]}")
        return r["data"]["taskId"]

    def poll(self, model, task_id):
        st, r = _req("GET", f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}", self.auth())
        if st >= 400:
            return "failed", [], f"status {st}: {r}"
        d = r.get("data", {})
        state = d.get("state")
        if state in ("waiting", "queuing", "generating"):
            return "pending", [], None
        if state == "fail":
            return "failed", [], f"{d.get('failCode')}: {d.get('failMsg')}"
        raw = d.get("resultJson")
        parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or {})
        return "done", _harvest_urls(parsed), None

    def balance(self):
        st, r = _req("GET", "https://api.kie.ai/api/v1/chat/credit", self.auth())
        if st >= 400:
            return None, str(r)
        credits = r.get("data")
        # заявленный курс: 1 кредит = $0.005
        return credits, f"{credits} кредитов ≈ ${float(credits) * 0.005:.2f}"


class Wavespeed:
    name = "wavespeed"
    env = "WAVESPEED_API_KEY"

    def auth(self):
        return f"Bearer {_key(self.env)}"

    def submit(self, model, payload):
        st, r = _req("POST", f"https://api.wavespeed.ai/api/v3/{model}", self.auth(), payload)
        if st >= 400 or not r.get("data", {}).get("id"):
            die(f"wavespeed submit {st}: {json.dumps(r, ensure_ascii=False)[:600]}")
        return r["data"]["id"]

    def poll(self, model, task_id):
        st, r = _req("GET", f"https://api.wavespeed.ai/api/v3/predictions/{task_id}/result", self.auth())
        if st >= 400:
            return "failed", [], f"status {st}: {r}"
        d = r.get("data", {})
        s = d.get("status")
        if s in ("created", "processing"):
            return "pending", [], None
        if s != "completed":
            return "failed", [], f"{s} / code={d.get('code')} {d.get('error')}"
        return "done", list(d.get("outputs") or []), None

    def balance(self):
        st, r = _req("GET", "https://api.wavespeed.ai/api/v3/balance", self.auth())
        if st >= 400:
            return None, str(r)
        b = r.get("data", {}).get("balance")
        return b, f"${b}"


PROVIDERS = {p.name: p() for p in (Fal, Kie, Wavespeed)}


def _harvest_urls(obj):
    """Вытаскивает http(s)-ссылки на медиа из ответа любой формы."""
    found = []

    def walk(o):
        if isinstance(o, str):
            if o.startswith("http") and any(
                e in o.lower() for e in
                (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm", ".mov", ".mp3", ".wav")
            ):
                found.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    # сохранить порядок, убрать дубли
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------- run

def download(url, dest_dir, stem):
    dest_dir.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(url.split("?")[0])[1] or ".bin"
    path = dest_dir / f"{stem}{ext}"
    n = 1
    while path.exists():
        path = dest_dir / f"{stem}-{n}{ext}"
        n += 1
    with urllib.request.urlopen(url, timeout=300) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def log_line(entry):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cmd_run(a):
    prov = PROVIDERS.get(a.provider) or die(f"неизвестный провайдер: {a.provider}")
    try:
        payload = json.loads(a.input)
    except json.JSONDecodeError as e:
        die(f"--input не разобрался как JSON: {e}")

    if a.dry_run:
        print(json.dumps({"provider": a.provider, "model": a.model,
                          "input": payload, "est_cost_usd": a.cost}, ensure_ascii=False, indent=2))
        return

    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%d-%H%M%S")
    task_id = prov.submit(a.model, payload)
    print(f"submitted: {a.provider} {a.model} task={task_id}", file=sys.stderr)

    delay, waited = POLL_START, 0.0
    while True:
        time.sleep(delay)
        waited += delay
        state, urls, err = prov.poll(a.model, task_id)
        if state == "done":
            break
        if state == "failed":
            log_line({"ts": started.isoformat(), "provider": a.provider, "model": a.model,
                      "task_id": task_id, "input": payload, "status": "failed",
                      "error": err, "est_cost_usd": 0.0, "files": []})
            die(f"задача провалилась: {err}", 3)
        if waited > a.timeout:
            die(f"таймаут {a.timeout}s, задача {task_id} ещё выполняется — "
                f"проверь позже вручную", 4)
        delay = min(delay * 1.5, POLL_MAX)
        print(f"  ... {int(waited)}s", file=sys.stderr)

    out_dir = Path(a.out) if a.out else OUT_DIR / started.strftime("%Y-%m-%d")
    files = []
    for i, u in enumerate(urls):
        stem = f"{stamp}-{a.model.replace('/', '_')}" + (f"-{i}" if len(urls) > 1 else "")
        files.append(str(download(u, out_dir, stem)))

    entry = {
        "ts": started.isoformat(),
        "provider": a.provider,
        "model": a.model,
        "task_id": task_id,
        "input": payload,
        "status": "ok",
        "est_cost_usd": a.cost,
        "note": a.note,
        "urls": urls,
        "files": files,
    }
    log_line(entry)
    print(json.dumps({"files": files, "urls": urls, "est_cost_usd": a.cost},
                     ensure_ascii=False, indent=2))


def cmd_balance(a):
    names = [a.provider] if a.provider else list(PROVIDERS)
    for n in names:
        p = PROVIDERS[n]
        if not os.environ.get(p.env):
            print(f"{n}: ключ не задан ({p.env})")
            continue
        _, human = p.balance()
        print(f"{n}: {human}")


def _read_log():
    if not LOG_PATH.exists():
        return []
    out = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def cmd_spent(a):
    rows = _read_log()
    if a.since == "today":
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = [r for r in rows if r.get("ts", "").startswith(today)]
    elif a.since != "all":
        rows = [r for r in rows if r.get("ts", "") >= a.since]
    total = sum(float(r.get("est_cost_usd") or 0) for r in rows)
    by = {}
    for r in rows:
        by[r["model"]] = by.get(r["model"], 0) + float(r.get("est_cost_usd") or 0)
    print(f"генераций: {len(rows)}   потрачено (оценка): ${total:.3f}")
    for m, v in sorted(by.items(), key=lambda x: -x[1]):
        print(f"  {m:<50} ${v:.3f}")


def cmd_log(a):
    for r in _read_log()[-a.last:]:
        prompt = str(r.get("input", {}).get("prompt", ""))[:70]
        print(f"{r.get('ts', '')[:19]}  {r.get('provider'):<10} {r.get('model'):<45} "
              f"${float(r.get('est_cost_usd') or 0):.3f}  {r.get('status')}  {prompt}")


def main():
    p = argparse.ArgumentParser(description="генерация через агрегаторы моделей")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="запустить генерацию")
    r.add_argument("--provider", required=True, choices=list(PROVIDERS))
    r.add_argument("--model", required=True)
    r.add_argument("--input", required=True, help="JSON с параметрами модели")
    r.add_argument("--cost", type=float, default=0.0, help="оценка стоимости в USD, идёт в лог")
    r.add_argument("--note", default="", help="пометка для лога")
    r.add_argument("--out", default="", help="куда класть файлы (по умолчанию generations/ГГГГ-ММ-ДД)")
    r.add_argument("--timeout", type=float, default=900, help="сколько ждать, секунд")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_run)

    b = sub.add_parser("balance", help="баланс провайдера")
    b.add_argument("--provider", choices=list(PROVIDERS))
    b.set_defaults(func=cmd_balance)

    s = sub.add_parser("spent", help="сколько потрачено по логу")
    s.add_argument("--since", default="today", help="today | all | ГГГГ-ММ-ДД")
    s.set_defaults(func=cmd_spent)

    l = sub.add_parser("log", help="последние генерации")
    l.add_argument("--last", type=int, default=20)
    l.set_defaults(func=cmd_log)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
