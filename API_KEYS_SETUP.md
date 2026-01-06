# API Keys Setup Guide

## Required API Keys

### 1. OpenAI API Key (REQUIRED)
**Purpose:** Powers the LLM for market analysis and superforecasting

**How to get it:**
1. Go to https://platform.openai.com/api-keys
2. Sign up or log in
3. Click "Create new secret key"
4. Copy the key (starts with `sk-...`)
5. Add to `.env` file: `OPENAI_API_KEY="sk-..."`

**Cost:** Pay-as-you-go
- GPT-3.5-turbo-16k: ~$0.003/1K tokens (default model)
- GPT-4: More expensive but better predictions

**Estimate:** ~$1-5/day for active trading depending on usage

---

### 2. Polygon Wallet Private Key (REQUIRED FOR TRADING)
**Purpose:** Execute trades on Polymarket

**How to get it:**
1. Install MetaMask or another Ethereum wallet
2. Create a new wallet OR create a separate trading wallet for safety
3. Switch network to **Polygon** in MetaMask
4. Fund with USDC on Polygon network
   - Bridge from Ethereum using https://wallet.polygon.technology/
   - OR buy directly on an exchange that supports Polygon USDC
   - Start with $10-20 for testing
5. Export private key from MetaMask:
   - Click account → Account Details → Show Private Key
   - Enter password → Copy private key
6. Add to `.env` file: `POLYGON_WALLET_PRIVATE_KEY="0x..."`

**IMPORTANT SECURITY:**
- ⚠️ NEVER share your private key
- ⚠️ Use a separate wallet just for trading (not your main wallet)
- ⚠️ Start with small amounts ($10-20) for testing
- ⚠️ .env file is in .gitignore - do NOT commit it

---

### 3. NewsAPI Key (OPTIONAL but recommended)
**Purpose:** Fetch news articles for market intelligence

**How to get it:**
1. Go to https://newsapi.org/
2. Click "Get API Key"
3. Sign up for FREE tier
4. Copy your API key
5. Add to `.env` file: `NEWSAPI_API_KEY="..."`

**Free Tier:** 100 requests/day (sufficient for testing)

---

### 4. Tavily API Key (OPTIONAL)
**Purpose:** Alternative search API for gathering market data

**How to get it:**
1. Go to https://tavily.com/
2. Sign up for account
3. Get API key from dashboard
4. Add to `.env` file: `TAVILY_API_KEY="..."`

**Note:** This is optional - the framework works fine with just NewsAPI

---

## Your .env File Should Look Like:

```bash
# REQUIRED
POLYGON_WALLET_PRIVATE_KEY="0xYOUR_PRIVATE_KEY_HERE"
OPENAI_API_KEY="sk-YOUR_OPENAI_KEY_HERE"

# OPTIONAL
NEWSAPI_API_KEY="YOUR_NEWSAPI_KEY_HERE"
TAVILY_API_KEY="YOUR_TAVILY_KEY_HERE"
```

---

## Testing Without Real Money

You can test the framework WITHOUT a Polygon wallet by:
1. Setting a dummy private key (won't execute real trades)
2. Running analysis commands only (no trading)
3. Using the CLI to explore markets and get predictions

Example test commands (no wallet needed):
```bash
# Get market data
python scripts/python/cli.py get-all-markets --limit 10

# Get news
python scripts/python/cli.py get-relevant-news "Bitcoin,crypto"

# Ask for predictions (requires OpenAI key only)
python scripts/python/cli.py ask-superforecaster "2024 Election" "Will Trump win?" "Yes"
```

---

## Next Steps After Getting Keys

1. Edit `.env` file and add your keys
2. Test the CLI commands
3. Run the autonomous trader with small amounts
4. Monitor and adjust strategy

---

## Estimated Costs

**Minimum to get started:**
- OpenAI API: $10 credit (lasts weeks for testing)
- Polygon USDC: $10-20 for initial trades
- NewsAPI: FREE

**Total: ~$20-30 to start testing**

**Monthly (active trading):**
- OpenAI: $30-100 depending on frequency
- Polygon USDC: Your trading capital
- NewsAPI: FREE (or $49/mo for Developer tier with more requests)

**Total: ~$30-150/month + trading capital**
