PYTHON ?= python3
CSV ?= path/to/ohlcv.csv
HTF_BIAS ?= NEUTRAL
MODE ?= RULE_ONLY
BARS ?=
LEDGER ?= state/paper-ledger.jsonl

.PHONY: install install-dev test signal backtest validate paper

install:
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

signal:
	$(PYTHON) -m xauusd_signal signal --csv "$(CSV)" --htf-bias "$(HTF_BIAS)" --mode "$(MODE)" $(if $(BARS),--bars "$(BARS)",)

backtest:
	$(PYTHON) -m xauusd_signal backtest --csv "$(CSV)" --htf-bias "$(HTF_BIAS)" --mode "$(MODE)" $(if $(BARS),--bars "$(BARS)",)

validate:
	$(PYTHON) -m xauusd_signal validate --csv "$(CSV)" --htf-bias "$(HTF_BIAS)" --mode "$(MODE)" $(if $(BARS),--bars "$(BARS)",)

paper:
	$(PYTHON) -m xauusd_signal paper --csv "$(CSV)" --htf-bias "$(HTF_BIAS)" --mode "$(MODE)" --ledger "$(LEDGER)" $(if $(BARS),--bars "$(BARS)",)
