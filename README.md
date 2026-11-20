# ДЗ 5. Расчёт из ДЗ 3 в Kubernetes

Вариант 6 — «Программист, разработчик на C и C++». Программа подсчёта навыков, пар и троек из
[ДЗ 3](https://github.com/ViktorVaskin98/itmo-de-hw3) в локальном kind-кластере: задание с пределами ресурсов
(OOMKilled и подбор предела по измеренному пику), RustFS из ДЗ 2 внутри кластера, расчёт параллельными
Indexed Job по сплитам файла, ожидание при нехватке CPU, вытеснение по приоритету, квота пространства имён.

Отчёт: [`hw5_kubernetes_vaskin_viktor.pdf`](hw5_kubernetes_vaskin_viktor.pdf).

## Что внутри

```
cluster/kind.yaml         kind: control-plane (hw5/pool=storage, порты 9100/9101 -> NodePort RustFS)
                          и два воркера (hw5/pool=batch, system-reserved cpu=8,memory=5Gi -> 4 CPU / 2,36 GiB)
Dockerfile                образ в две стадии: uv ставит зависимости в /opt/venv, в итоговый образ идёт только venv
k8s/
  00-namespace.yaml       пространство hw5, ключи S3
  05-priority.yaml        PriorityClass: batch-low, batch-high, storage-critical
  10-hw3-job.yaml         расчёт ДЗ 3 одним подом: requests/limits, podFailurePolicy (137 -> FailJob)
  20-rustfs.yaml          RustFS 1.0.1: StatefulSet, 8 PVC (EC 4+4), Service NodePort
  21-migrate-job.yaml     перенос бакета hh-lake из rustfs-lab в кластер с проверкой md5
  30-map-job.yaml         Indexed Job map: индекс пода = номер сплита, backoffLimitPerIndex, podFailurePolicy
  31-reduce-job.yaml      Indexed Job reduce: индекс = партиция
  32-commit-job.yaml      сведение счётчиков, _SUCCESS и сверка с ДЗ 3
  33-verify-job.yaml      сверка произвольного префикса с ДЗ 3
  40-quota.yaml           пространство hw5-quota с ResourceQuota
  41-limitrange.yaml      значения requests/limits по умолчанию
src/hhlake/
  mapreduce/              MapReduce из ДЗ 3 без изменений
  verify.py               сверка двух результатов (FULL OUTER JOIN в DuckDB); добавлен вывод топ-N пар
  kube/
    memwatch.py           обёртка команды пода: память cgroup v2 раз в 0,1 с, memory.peak, memory.events, cpu.stat;
                          пересылает SIGTERM дочернему процессу (PID 1 сам его игнорирует)
    sizing.py             предел по пику: ceil(max memory.peak x 1,2 / 64 MiB) x 64 MiB
    maptask.py            задача map для Indexed Job: сплит по JOB_COMPLETION_INDEX, вывод в shuffle/<run>/mNNNN/
    reducetask.py         задача reduce: партиция из всех сплитов, part-r-*.csv в results/k8s/<run>/
    commit.py             сверка сумм map и reduce, _job.json и _SUCCESS
    shuffle.py, plan.py   раскладка префиксов, план сплитов
    migrate.py            копирование между двумя S3 с md5
    clean.py              очистка префиксов прогона перед повтором
scripts/                  01_cluster ... 08_quota и run_all; env.ps1 подставляет параметры в шаблоны k8s/
tools/                    временная шкала подов, графики, сборка фрагментов логов для отчёта
tests/                    pytest: сплиты и вариант из ДЗ 3, подбор предела, сведение счётчиков
logs/                     выводы всех этапов; logs/manifests/ — манифесты в том виде, в каком применялись;
                          logs/pods/ — журналы подов; logs/state/ — поды, задания и события в JSON;
                          logs/discarded/run1/ — первый прогон, где RustFS упал по OOM
report/                   LaTeX-исходник отчёта
```

## Как запустить

Нужны Docker Desktop (WSL 2), [uv](https://docs.astral.sh/uv/), `kubectl` (идёт с Docker Desktop) и RustFS из ДЗ 2–3
(контейнер `rustfs-lab`, бакет `hh-lake` с сырым CSV и эталоном `results/mapreduce`). `kind` v0.33.0 скрипт
`01_cluster.ps1` скачивает в `C:\itmo\tools` (или в `$env:HW5_TOOLS`) и проверяет sha256. Путь к CSV на хосте
и к `results/stacks` из репозитория ДЗ 3 задаются в `scripts/env.ps1` (`$env:HW5_CSV`, `$env:HW3_STACKS`).
Ключи `labadmin` / `labsecret123` — локальные учебные ключи RustFS из ДЗ 2.

```powershell
uv sync
uv run pytest
.\scripts\run_all.ps1      # кластер с нуля и все этапы; время этапов пишется в logs/run_all.txt (последний прогон ~20 мин)
```

Отчёт собирается из журналов: `uv run python tools/build_assets.py`, `uv run --group report python tools/figures.py`,
затем дважды `xelatex -output-directory=build main.tex` в `report/`.

Скрипты этапов можно запускать по отдельности (на поднятом кластере):

```powershell
.\scripts\03_memory.ps1    # OOMKilled на 256Mi, три замера, подбор предела, проверка и граница снизу
.\scripts\05_parallel.ps1  # пробный прогон, пределы map/reduce, параллельный расчёт и сверка с ДЗ 3
.\scripts\07_preemption.ps1
```

## Результаты

Числа ниже — из последнего прогона (`logs/`):

- 256Mi — `OOMKilled`, код 137; пик по `memory.peak` в трёх запусках 550–551 MiB, предел 704Mi
  (ceil(551 × 1,2 / 64) × 64); три запуска с ним успешны, 512Mi (ниже пика анонимной памяти 534 MiB) — снова `OOMKilled`;
- RustFS в кластере: 8 томов по 204 MiB (EC 4+4), md5 копии совпал с исходным файлом;
- Indexed Job: 26 подов map, 4 reduce, commit — совпадение с ДЗ 3 по всем 100 692 ключам, топ-10 пар те же,
  `skills/pairs/triples.csv` побайтно совпали с `results/stacks` из репозитория ДЗ 3;
- 1500m CPU на под: по два пода на воркер, остальные в `Pending` с `Insufficient cpu`, дольше всех ждал 12 с;
- срочный расчёт `batch-high` вытеснил два пода `batch-low` (код 143 после SIGTERM), их индексы пересчитаны,
  оба результата совпали с ДЗ 3;
- квота 3 CPU: поды сверх квоты не создаются (`FailedCreate: exceeded quota`), идут волнами по три.
