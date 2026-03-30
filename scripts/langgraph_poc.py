"""
LangGraph Proof of Concept - Validate that LangGraph + Ollama works on Oracle.

This is a minimal test: create a supervisor with one worker agent,
send a task, and verify the full loop completes.

Run: C:\Python312\python.exe scripts\langgraph_poc.py
"""
import json
import os
import sys
from datetime import datetime

# Ensure rudy is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_langgraph_ollama():
    """Test LangGraph with Ollama qwen2.5:7b."""
    results = {"timestamp": datetime.now().isoformat(), "tests": []}
    
    # Test 1: Can we import langgraph?
    try:
        from langgraph.graph import StateGraph, START, END
        from langgraph.prebuilt import ToolNode
        results["tests"].append({"name": "import_langgraph", "status": "pass"})
    except ImportError as e:
        results["tests"].append({"name": "import_langgraph", "status": "fail", "error": str(e)})
        print(json.dumps(results, indent=2))
        return results
    
    # Test 2: Can we import langchain-ollama?
    try:
        from langchain_ollama import ChatOllama
        results["tests"].append({"name": "import_langchain_ollama", "status": "pass"})
    except ImportError as e:
        results["tests"].append({"name": "import_langchain_ollama", "status": "fail", "error": str(e)})
        print(json.dumps(results, indent=2))
        return results
    
    # Test 3: Can we connect to Ollama?
    try:
        llm = ChatOllama(model="qwen2.5:7b", temperature=0)
        response = llm.invoke("Say 'Robin reporting for duty' and nothing else.")
        content = response.content if hasattr(response, 'content') else str(response)
        results["tests"].append({
            "name": "ollama_connection",
            "status": "pass",
            "response_preview": content[:200]
        })
    except Exception as e:
        results["tests"].append({"name": "ollama_connection", "status": "fail", "error": str(e)})
        print(json.dumps(results, indent=2))
        return results
    
    # Test 4: Can we build a simple StateGraph?
    try:
        from typing import Annotated, TypedDict
        from langgraph.graph.message import add_messages
        
        class State(TypedDict):
            messages: Annotated[list, add_messages]
        
        def chatbot(state: State):
            return {"messages": [llm.invoke(state["messages"])]}
        
        graph_builder = StateGraph(State)
        graph_builder.add_node("chatbot", chatbot)
        graph_builder.add_edge(START, "chatbot")
        graph_builder.add_edge("chatbot", END)
        graph = graph_builder.compile()
        
        results["tests"].append({"name": "build_stategraph", "status": "pass"})
    except Exception as e:
        results["tests"].append({"name": "build_stategraph", "status": "fail", "error": str(e)})
        print(json.dumps(results, indent=2))
        return results
    
    # Test 5: Can we invoke the graph?
    try:
        from langchain_core.messages import HumanMessage
        
        output = graph.invoke({"messages": [HumanMessage(content="What is 2+2? Answer with just the number.")]})
        last_msg = output["messages"][-1]
        content = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
        results["tests"].append({
            "name": "invoke_graph",
            "status": "pass",
            "response_preview": content[:200]
        })
    except Exception as e:
        results["tests"].append({"name": "invoke_graph", "status": "fail", "error": str(e)})
    
    return results

if __name__ == "__main__":
    print("=" * 50)
    print("LangGraph + Ollama Proof of Concept")
    print("=" * 50)
    
    results = test_langgraph_ollama()
    
    passed = sum(1 for t in results["tests"] if t["status"] == "pass")
    total = len(results["tests"])
    
    print(f"\nResults: {passed}/{total} tests passed")
    for t in results["tests"]:
        icon = "OK" if t["status"] == "pass" else "FAIL"
        print(f"  [{icon}] {t['name']}")
        if "response_preview" in t:
            print(f"       Response: {t['response_preview'][:80]}")
        if "error" in t:
            print(f"       Error: {t['error'][:100]}")
    
    # Save results
    from pathlib import Path
    result_path = Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "rudy-data" / "langgraph-poc-result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull results: {result_path}")
    print("DONE")
