# Drova Dash

https://drova-top.streamlit.app/

Streamlit-приложение для аналитики изменений состояния станций и BUSY-сессий:
- рейтинги по станциям/продуктам/городам/железу
- карты и treemap
- скользящие метрики активности и наигранных часов

## Что нужно для запуска

- Python 3.12+
- SQLite-база рядом с приложением:
  - по умолчанию: `stations20260220.db`

## Установка и локальный запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Приложение откроется в браузере и начнет читать данные из `stations20260220.db`.

## Данные и ожидания к БД

Приложение использует:
- `station_changes`:
  - `id`, `uuid`, `old_state`, `new_state`, `old_product_id`, `new_product_id`, `changed_at`
- `server_info`:
  - `uuid`, `name`, `city_name`, `processor`, `graphic_names`, `free_trial`,
    `product_number`, `ram_bytes`, `graphic_ram_bytes`, `longitude`, `latitude`

Скрипт `server_info_fetcher.py` может заполнить/обновить `server_info`:

```bash
python3 server_info_fetcher.py stations20260220.db --verbose
```

## Как устроен код

Точка входа:
- `streamlit_app.py` — тонкий оркестратор (контролы -> загрузка -> фильтры -> агрегации -> рендер)

Модули:
- `app/config.py` — константы и настройки
- `app/data_access.py` — чтение из SQLite/API + `st.cache_data`
- `app/pipeline.py` — очистка событий и построение BUSY-интервалов
- `app/preparation.py` — расчёт длительностей и enrichment метаданными
- `app/workflow.py` — загрузка и подготовка данных (со спиннерами)
- `app/filters.py` — UI-контролы сайдбара и применение фильтров
- `app/aggregations.py` — агрегации и производные метрики
- `app/views.py` — визуализации (Altair/Plotly, таблицы, download)

## Основной поток данных

1. Загрузка `station_changes` из SQLite
2. Очистка и сортировка событий
3. Построение BUSY-интервалов (`started_at`, `ended_at`)
4. Расчёт `duration_sec` и `duration_minutes`
5. Фильтр по:
   - дате
   - максимальной длине сессии
6. Enrichment:
   - `server_info` (железо/гео/признаки)
   - словари станций/продуктов
7. Фильтры сайдбара (станция/продукт/город/CPU/GPU/free trial/диапазоны)
8. Агрегации и рендер графиков/таблиц

## Скользящие метрики

Контрол:
- `Sliding window (days)` в `Controls`
- диапазон: от `1` до `90` дней (статический максимум)

Метрики:
- `active_stations_window`: число уникальных `uuid` в окне
- `played_hours_window`: сумма часов (`duration_sec / 3600`) в окне

Технически:
- окно считается по дате `started_at` (нормализованной до дня)
- отображаются только **полные окна**
- старт графика = `max(selected_start + window - 1, first_data_date + window - 1)`

## Деплой на Streamlit Community

Этот проект использует фиксированные версии в `requirements.txt`:
- `streamlit==1.50.0`
- `altair==5.5.0`
- `pandas==2.3.3`
- `plotly==6.3.1`
- `requests==2.32.5`

Почему так:
- избегаем несовместимости вида `streamlit 1.x` + неподходящая мажорная версия `altair`

Если после пуша деплой не подхватил изменения:
1. Открой приложение в Streamlit Community
2. Нажми `Reboot app` или `Redeploy`

## Частые проблемы

- `Не найден файл БД: stations20260220.db`
  - положи файл БД в корень проекта рядом с `streamlit_app.py`

- Пустые графики после фильтров
  - расширь date range
  - ослабь фильтры по station/product/city/hardware
  - проверь лимит `Max session length (hours)`

## Быстрая навигация по изменениям

Если нужно добавить новую аналитику:
1. Расчёт в `app/aggregations.py`
2. UI в `app/views.py`
3. Вызов в `streamlit_app.py`

Если нужен новый фильтр:
1. Контрол в `app/filters.py`
2. Логика в `apply_sidebar_filters(...)`
3. (опц.) влияние на агрегации/графики
