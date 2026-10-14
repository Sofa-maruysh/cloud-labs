# Результаты проверок

Запустите из корня лабораторной:

```powershell
.\scripts\collect-evidence.ps1
```

Скрипт создаст здесь:

- `check-run.txt` — проверку всех требований;
- `compose-ps.txt` — состояние контейнеров;
- `nginx-test.txt` — результат проверки и полный конфиг nginx;
- `docker-version.txt` — версии Docker и Compose;
- `images.txt` — использованные образы;
- `compose-logs.txt` — журналы сервисов.

Перед коммитом убедитесь, что `check-run.txt` заканчивается строкой `FAIL=0`.

