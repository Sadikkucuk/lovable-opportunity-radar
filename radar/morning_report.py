"""Generate the immutable morning operational snapshot from persisted evidence.

This job NEVER researches or changes the published catalog. Delivery via email
depends on the owner's ChatGPT/GitHub notification configuration.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def read(root, name):
    path = root / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def build(root, now):
    root = Path(root)
    config = read(root, "state/v2/config.json")
    if config.get("mode") != "active":
        return None
    local = now.astimezone(ZoneInfo("Europe/Istanbul"))
    # This script may run after the overnight boundary but never before 07:00.
    if local.hour < 7:
        raise ValueError("morning report is only available after the 07:00 cutoff")
    day = local.date().isoformat()
    status = read(root, "state/v2/status.json")
    health = read(root, "state/v2/health.json")
    sources = read(root, "docs/status.json")
    feed = read(root, "docs/latest.json")
    runs = [r for r in status.get("runs", []) if r.get("run_id", "").startswith(day+"-")]
    actual = runs[0] if runs else {}
    catalog = read(root, "state/idea_catalog.json")
    results = {
        "schema_version": 1, "date": day, "generated_at": now.isoformat(),
        "source_count": sources.get("source_count"), "source_success": sources.get("successful_sources"),
        "source_failure": sources.get("failed_sources"), "feed_generated_at": feed.get("generated_at"),
        "feed_items": feed.get("item_count"), "feed_cap": feed.get("aggregate_limit"),
        "catalog_ideas": len(catalog.get("ideas", [])),
        "preserved_baseline": 91, "jobs": status.get("counts", {}),
        "night_run": actual, "health": {"state": health.get("state"),
            "alerts": health.get("alerts", []),
            "last_verified_progress_at": health.get("last_verified_progress_at")},
        "research_complete": bool(actual and actual.get("processing_status") in ("complete", "complete_with_gaps")),
        "site_delivery": actual.get("site_delivery", "not_verified"),
        "email_delivery": "requires_user_notification_settings_and_delivery_test"
    }
    return results


def render(data):
    counts = data["jobs"]
    done = counts.get("done", 0)
    pending = sum(v for k, v in counts.items() if k not in ("done", "unverified", "rejected", "failed"))
    lines = [f"# AIStartup Radar — {data['date']} sabah özeti", "",
             f"- Haber kaynakları: {data['source_success']}/{data['source_count']} başarılı; başarısız: {data['source_failure']}",
             f"- RSS son üretim: {data['feed_generated_at']}; mevcut havuz: {data['feed_items']}",
             f"- Kanonik katalog: {data['catalog_ideas']} fikir; koruma hedefi: en az 91",
             f"- Toplam tamamlanan iş: {done}; bekleyen/aktif iş: {pending}",
             f"- Bugünkü araştırma: {data['night_run'].get('processing_status', 'not_started_or_not_reconciled')}",
             f"- Bugünkü haber kapsaması: {data['night_run'].get('articles_processed', 0)} / {data['night_run'].get('articles_expected', 'unknown')}",
             f"- Günlük doğrulama kararları: {json.dumps(data['night_run'].get('validation_decisions', {}), ensure_ascii=False)}",
             f"- Sağlık: {data['health']['state']}; alarmlar: {len(data['health']['alerts'])}",
             f"- Son doğrulanmış ilerleme: {data['health']['last_verified_progress_at']}",
             f"- Web sitesi teslimi: {data['site_delivery']}",
             f"- Gece tamamlama: {'evet' if data['research_complete'] else 'hayır; eksik işler ertesi geceye devreder'}",
             "", "## Açık alarmlar"]
    for alarm in data["health"]["alerts"]:
        lines.append(f"- {alarm.get('code')}: worker={alarm.get('worker')}; {alarm.get('user_action', '')}")
    if not data["health"]["alerts"]:
        lines.append("- Bu sağlık anlık görüntüsünde açık alarm yok.")
    lines += ["", "## Sonraki adım",
              "Açık işleri mevcut immutable iş kuyruğunda koru; kalite ve kanıt koşullarını gevşetme.",
              "Bu rapor GitHub kayıtlarından üretildi; e-posta teslim edildiği anlamına gelmez.", ""]
    return "\n".join(lines)


def main():
    root = Path(".")
    data = build(root, datetime.now(timezone.utc))
    if data is None:
        print("Radar maintenance: morning report not generated.")
        return
    day = data["date"]
    folder = root / "docs/radar/reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (day + ".md")
    if not path.exists():
        path.write_text(render(data), encoding="utf-8")
        (folder / (day + ".json")).write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(path)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
