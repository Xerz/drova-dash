# Реальные Данные + GitHub Pages

## Summary

- HTML-макет подключен к реальным данным из `stations20260505.db`.
- Генератор пишет локальный preview в `reports/monthly_infographics.html` и Pages artifact в `site/index.html`.
- GitHub Actions workflow генерирует `site/index.html` на push в `master` и публикует его через GitHub Pages.
- Текущая БД содержит события до `2026-04-22 07:26:40`; майских данных нет.

## Implementation

- CLI: `generate_monthly_infographics.py`.
- Основные аргументы:
  - `--db stations20260505.db`
  - `--output site/index.html`
  - `--max-session-hours 30`
  - `--cache-dir reports/.cache`
- Расчеты не импортируют Streamlit: SQLite load, BUSY-интервалы, фильтр длинных сессий, клиппинг по месяцам.
- Месяцы отчета: полные месяцы плюс последний доступный неполный месяц. Для текущей БД: `2025-08` ... `2026-04`, где апрель помечен как частичный.
- Product catalog берется из `PRODUCTS_URL`; desktop/sandbox определяется по `useDefaultDesktop`.
- Server `has_desktop` считается по public `product_list`: сервер с desktop, если в `product_list` есть хотя бы один desktop-продукт.

## Metrics

- Desktop/sandbox по BUSY-часам:
  - все активные серверы месяца;
  - только активные серверы с desktop.
- Топ-10 станций по clipped BUSY-часам:
  - среди всех;
  - среди серверов с desktop;
  - среди серверов без desktop.
- Топ-5 CPU/GPU: по количеству уникальных активных станций месяца.
- Соотношение серверов с desktop / без desktop: среди активных станций месяца.
- Unknown product/server metadata не смешивается с sandbox; предупреждения выводятся в HTML.

## GitHub Pages

- Workflow: `.github/workflows/pages.yml`.
- Triggers: push в `master` и ручной `workflow_dispatch`.
- Workflow steps: checkout, setup Python 3.12, install requirements, restore API cache, run generator, upload Pages artifact, deploy Pages.
- Pages-сайт будет публичным после push и настройки repository Pages source на GitHub Actions.

## Test Plan

- `python3 generate_monthly_infographics.py --self-test`
- `python3 -m py_compile generate_monthly_infographics.py`
- `python3 -m html.parser reports/monthly_infographics_mockup.html`
- `python3 -m html.parser reports/monthly_infographics.html`
- `python3 -m html.parser site/index.html`
- Browser smoke: открыть `reports/monthly_infographics.html`, проверить апрель по умолчанию, sticky month tabs, переключение месяцев и срезов топа станций.
