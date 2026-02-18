#!/bin/bash
cd /app

# 1. Inject bugs into the clean codebase
python3 /tests/apply_bugs.py

# 2. If solution exists, apply it (fixes the injected bugs)
if [ -f /solution/solve.sh ]; then
    bash /solution/solve.sh
fi

# 3. Run migrations and tests
pip install pytest > /dev/null 2>&1
mkdir -p /logs/verifier
python manage.py migrate --run-syncdb > /dev/null 2>&1

PYTHONPATH=/app DJANGO_SETTINGS_MODULE=hc.settings pytest /tests/test_solution.py -v 2>&1

if [ $? -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
