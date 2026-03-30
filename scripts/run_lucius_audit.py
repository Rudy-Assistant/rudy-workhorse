import sys
sys.path.insert(0, "C:/Users/ccimi/Desktop/rudy-workhorse")
from rudy.agents.lucius_fox import LuciusFox

lucius = LuciusFox()
lucius.execute(mode="full_audit")
print("Lucius audit complete:", lucius.status.get("summary", ""))
