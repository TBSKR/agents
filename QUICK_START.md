# Quick Start Guide

## ✅ Installation Complete!

Your Polymarket AI trading agent is ready to use. Here's what was installed:

- **Python 3.12** virtual environment
- **150+ packages** including LangChain, OpenAI, ChromaDB, Web3, and Polymarket clients
- **Framework code** from official Polymarket Agents repository

---

## 🔑 Next Steps: Get API Keys

Before you can run the agent, you need API keys. See `API_KEYS_SETUP.md` for detailed instructions.

**Minimum required:**
1. **OpenAI API Key** - For LLM analysis (https://platform.openai.com/api-keys)
2. **Polygon Wallet Private Key** - For trading (see API_KEYS_SETUP.md)

**Optional but recommended:**
3. **NewsAPI Key** - For news intelligence (https://newsapi.org - FREE tier available)

Once you have your keys, edit `.env` file:
```bash
nano .env
```

---

## 🚀 Running the Agent

### Activate the virtual environment:
```bash
source .venv/bin/activate
```

### Set Python path (required):
```bash
export PYTHONPATH="."
```

### Test Commands (NO WALLET NEEDED):

**1. Test imports:**
```bash
python -c "from agents.polymarket.polymarket import Polymarket; print('Success!')"
```

**2. Ask OpenAI directly (requires OpenAI API key only):**
```bash
python -c "
from agents.application.executor import Executor
exec = Executor()
response = exec.get_llm_response('What is Polymarket?')
print(response)
"
```

### Trading Commands (REQUIRES WALLET):

**Get top markets by spread:**
```bash
python scripts/python/cli.py get-all-markets --limit 10 --sort-by spread
```

**Get market events:**
```bash
python scripts/python/cli.py get-all-events --limit 5
```

**Get relevant news:**
```bash
python scripts/python/cli.py get-relevant-news "Bitcoin,Trump,Election"
```

**Ask superforecaster for prediction:**
```bash
python scripts/python/cli.py ask-superforecaster "2024 Election" "Will Trump win?" "Yes"
```

**Ask LLM about current markets:**
```bash
python scripts/python/cli.py ask-polymarket-llm "What crypto markets should I trade?"
```

**Run autonomous trader (WILL ANALYZE but NOT execute unless you uncomment line 60 in agents/application/trade.py):**
```bash
python agents/application/trade.py
```

---

## 📊 Autonomous Trading Flow

The autonomous agent (`agents/application/trade.py`) does the following:

1. Fetches all tradeable events from Polymarket
2. Uses RAG to filter events you'd profit from trading
3. Maps filtered events to specific markets
4. Filters markets using AI analysis
5. Uses **superforecasting** to predict outcomes
6. Calculates optimal trade (price, size, side)
7. Executes trade (currently COMMENTED OUT for safety)

---

## ⚠️ Important Safety Notes

**Line 60 in `agents/application/trade.py` is commented out:**
```python
# Please refer to TOS before uncommenting: polymarket.com/tos
# trade = self.polymarket.execute_market_order(market, amount)
```

**This means:**
- ✅ The agent WILL analyze markets and calculate trades
- ❌ The agent WILL NOT execute actual trades
- ⚠️ Uncomment line 60 when you're ready to trade with real money

**Testing Safely:**
1. Start with `.env` containing dummy values
2. Test the analysis logic without trading
3. Add real API keys when ready
4. Fund wallet with $10-20 USDC for initial tests
5. Uncomment line 60 only after you're confident

---

## 🛠 Troubleshooting

**Error: "A private key is needed"**
→ Add your `POLYGON_WALLET_PRIVATE_KEY` to `.env` file

**Error: "OpenAI API key is required"**
→ Add your `OPENAI_API_KEY` to `.env` file

**Error: "ModuleNotFoundError"**
→ Make sure you activated the virtual environment: `source .venv/bin/activate`

**Error: "No module named 'agents'"**
→ Set Python path: `export PYTHONPATH="."`

---

## 📝 Project Structure

```
polymarket-agents/
├── .env                    # Your API keys (DO NOT COMMIT)
├── .venv/                  # Python virtual environment
├── agents/
│   ├── application/
│   │   ├── trade.py       # Autonomous trading script
│   │   ├── executor.py    # LLM execution logic
│   │   ├── prompts.py     # Superforecasting prompts
│   ├── connectors/
│   │   ├── chroma.py      # RAG vector database
│   │   ├── news.py        # News API integration
│   ├── polymarket/
│   │   ├── polymarket.py  # Polymarket API client
│   │   ├── gamma.py       # Gamma market data
│   └── utils/
│       └── objects.py     # Data models
├── scripts/
│   └── python/
│       └── cli.py         # Command-line interface
├── API_KEYS_SETUP.md      # Detailed API key instructions
├── QUICK_START.md         # This file
└── requirements.txt       # Python dependencies
```

---

## 🎯 Recommended Next Steps

1. **Get API keys** (see API_KEYS_SETUP.md)
2. **Test with analysis only** (no trading)
3. **Run superforecaster** on test questions
4. **Create RAG database** of markets you're interested in
5. **Paper test** the autonomous trader
6. **Fund wallet** with small amount ($10-20)
7. **Uncomment line 60** and make first real trade
8. **Monitor and adjust** strategy based on results

---

## 💡 Strategy Ideas

**For Development:**
- Test different LLM prompts for better predictions
- Add custom filtering logic for specific market categories
- Implement position sizing based on confidence scores
- Create scheduled runs (cron jobs) for periodic analysis
- Build dashboard to visualize agent performance

**For Production:**
- Deploy to VPS for 24/7 operation
- Add monitoring and alerting
- Implement risk management rules
- Create multiple agents for different strategies
- Log all trades and analyze performance

---

## 🔗 Useful Links

- [Polymarket Agents GitHub](https://github.com/Polymarket/agents)
- [Polymarket Documentation](https://docs.polymarket.com/)
- [OpenAI API Docs](https://platform.openai.com/docs)
- [LangChain Documentation](https://python.langchain.com/)

---

Good luck building your profitable Polymarket AI agent! 🚀
