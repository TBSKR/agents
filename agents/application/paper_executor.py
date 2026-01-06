"""
Paper Trading Executor - No blockchain credentials required.
Uses only public Gamma API and OpenAI for AI predictions.
"""

import os
import json
import ast
import re
from typing import List, Dict, Any
import math

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from agents.polymarket.gamma import GammaMarketClient as Gamma
from agents.connectors.chroma import PolymarketRAG as Chroma
from agents.utils.objects import SimpleEvent, SimpleMarket
from agents.application.prompts import Prompter


def retain_keys(data, keys_to_retain):
    if isinstance(data, dict):
        return {
            key: retain_keys(value, keys_to_retain)
            for key, value in data.items()
            if key in keys_to_retain
        }
    elif isinstance(data, list):
        return [retain_keys(item, keys_to_retain) for item in data]
    else:
        return data


class PaperExecutor:
    """Executor for paper trading - no Polymarket credentials needed."""
    
    def __init__(self, default_model='gpt-3.5-turbo') -> None:
        load_dotenv()
        self.prompter = Prompter()
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        self.llm = ChatOpenAI(
            model=default_model,
            temperature=0,
        )
        self.gamma = Gamma()
        self.chroma = Chroma()

    def get_llm_response(self, user_input: str) -> str:
        system_message = SystemMessage(content=str(self.prompter.market_analyst()))
        human_message = HumanMessage(content=user_input)
        messages = [system_message, human_message]
        result = self.llm.invoke(messages)
        return result.content

    def get_superforecast(self, event_title: str, market_question: str, outcome: str) -> str:
        messages = self.prompter.superforecaster(
            description=event_title, question=market_question, outcome=outcome
        )
        result = self.llm.invoke(messages)
        return result.content

    def filter_events_with_rag(self, events: List[SimpleEvent]) -> List:
        prompt = self.prompter.filter_events()
        print(f"   ... filtering with RAG prompt")
        return self.chroma.events(events, prompt)

    def map_filtered_events_to_markets(self, filtered_events: List) -> List[SimpleMarket]:
        markets = []
        for e in filtered_events:
            data = json.loads(e[0].json())
            market_ids = data["metadata"]["markets"].split(",")
            for market_id in market_ids:
                try:
                    market_data = self.gamma.get_market(market_id)
                    formatted_market_data = self._map_api_to_market(market_data)
                    markets.append(formatted_market_data)
                except Exception as ex:
                    print(f"   Warning: Could not fetch market {market_id}: {ex}")
        return markets

    def _map_api_to_market(self, market) -> dict:
        """Map Gamma API response to market dict (without needing Polymarket class)."""
        return {
            "id": int(market["id"]),
            "question": market["question"],
            "end": market["endDate"],
            "description": market["description"],
            "active": market["active"],
            "funded": market.get("funded", False),
            "rewardsMinSize": float(market.get("rewardsMinSize", 0) or 0),
            "rewardsMaxSpread": float(market.get("rewardsMaxSpread", 0) or 0),
            "spread": float(market.get("spread", 0) or 0),
            "outcomes": str(market["outcomes"]),
            "outcome_prices": str(market["outcomePrices"]),
            "clob_token_ids": str(market.get("clobTokenIds", [])),
        }

    def filter_markets(self, markets) -> List[tuple]:
        prompt = self.prompter.filter_markets()
        print(f"   ... filtering markets with RAG")
        return self.chroma.markets(markets, prompt)

    def source_best_trade(self, market_object) -> str:
        market_document = market_object[0].dict()
        market = market_document["metadata"]
        outcome_prices = ast.literal_eval(market["outcome_prices"])
        outcomes = ast.literal_eval(market["outcomes"])
        question = market["question"]
        description = market_document["page_content"]

        prompt = self.prompter.superforecaster(question, description, outcomes)
        print(f"   ... getting AI prediction")
        result = self.llm.invoke(prompt)
        content = result.content

        print(f"   AI says: {content[:100]}...")
        
        prompt = self.prompter.one_best_trade(content, outcomes, outcome_prices)
        print(f"   ... calculating best trade")
        result = self.llm.invoke(prompt)
        trade_content = result.content

        print(f"   Trade recommendation: {trade_content[:100]}...")
        return trade_content

    def format_trade_prompt_for_execution(self, best_trade: str) -> float:
        data = best_trade.split(",")
        size = re.findall(r"\d+\.?\d*", data[1])[0]
        return float(size)
