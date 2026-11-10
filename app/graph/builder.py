from langgraph.graph import StateGraph, START, END
from app.services.data_processing import process_sources
from app.services.web_search import collect_web_content
from app.services.hacker_news import collect_hackernews_content
from app.services.substack import collect_substack_content
from app.services.send_mail import send_topic_review, receive_topic_review, send_topic_direction, send_draft_review, receive_draft_review
from app.services.linkedin import publish_approved_post
from app.services.preference_learning import learn_preferences
from app.db.client import get_checkpointer




from app.graph.state import ResearchState
from app.services.topic_review import initail_states, route_after_review, route_after_filter
# from app.services.topic_review import review_topics, route_after_review
from app.agents.topic_review_agent import filter_topics
from app.agents.summarizer import summarize_profile
from app.agents.search_topics import search_topics
from app.agents.topic_summarizer import summarize_topic
from app.agents.briefer import create_brief
from app.autonomous.researcher import research
from app.autonomous.writer import write_post
from app.autonomous.reviewer import review_post
from app.autonomous.feedback_processor import process_feedback
from app.autonomous.supervisor import supervise, route_supervisor
from app.autonomous.draft_clarification import request_draft_clarification



builder = StateGraph(ResearchState)
builder.add_node("summarize_profile", summarize_profile)
builder.add_node("search_topics", search_topics)


builder.add_node("collect_web_content", collect_web_content)
builder.add_node("collect_hackernews_content", collect_hackernews_content)
builder.add_node("collect_substack_content", collect_substack_content)
builder.add_node("process_sources", process_sources)
builder.add_node("filter_topics", filter_topics)
builder.add_node("send_topic_review", send_topic_review)
builder.add_node("receive_topic_review", receive_topic_review)
builder.add_node("send_topic_direction", send_topic_direction)
builder.add_node("summarize_topic", summarize_topic)
builder.add_node("create_brief", create_brief)
builder.add_node("researcher", research)
builder.add_node("writer", write_post)
builder.add_node("quality_review", review_post)
builder.add_node("supervisor", supervise)
builder.add_node("feedback_processor", process_feedback)
builder.add_node("request_draft_clarification", request_draft_clarification)
builder.add_node("send_draft_review", send_draft_review)
builder.add_node("receive_draft_review", receive_draft_review)
builder.add_node("publish_linkedin", publish_approved_post)
builder.add_node("learn_preferences", learn_preferences)
# builder.add_node("review_topics", review_topics)
builder.add_node("initail_states", initail_states)




builder.add_edge(START, "summarize_profile")
builder.add_edge("summarize_profile", "search_topics")
builder.add_edge("search_topics", "initail_states")

builder.add_edge("initail_states", "collect_web_content")
builder.add_edge("initail_states", "collect_hackernews_content")
builder.add_edge("initail_states", "collect_substack_content")
builder.add_edge(
    ["collect_web_content", "collect_hackernews_content", "collect_substack_content"],
    "process_sources",
)
builder.add_edge("process_sources", "filter_topics")
builder.add_conditional_edges("filter_topics", route_after_filter, {
    "send_topic_review": "send_topic_review", "send_topic_direction": "send_topic_direction",
})
builder.add_edge("send_topic_review", "receive_topic_review")
builder.add_edge("send_topic_direction", "receive_topic_review")
builder.add_conditional_edges("receive_topic_review", route_after_review, {
    "summarize_topic": "summarize_topic", "search_topics": "search_topics",
    "filter_topics": "filter_topics", "send_topic_direction": "send_topic_direction",
})
builder.add_edge("summarize_topic", "create_brief")
builder.add_edge("create_brief", "researcher")
builder.add_edge("researcher", "supervisor")
builder.add_conditional_edges("supervisor", route_supervisor, {
    name: name for name in ("writer", "feedback_processor", "send_draft_review",
                           "request_draft_clarification", "publish_linkedin", END)
})
builder.add_edge("feedback_processor", "supervisor")
builder.add_edge("writer", "quality_review")
builder.add_edge("quality_review", "supervisor")
builder.add_edge("send_draft_review", "receive_draft_review")
builder.add_edge("request_draft_clarification", "receive_draft_review")
builder.add_edge("receive_draft_review", "supervisor")
builder.add_edge("publish_linkedin", "learn_preferences")
builder.add_edge("learn_preferences", END)

# builder.add_edge("initail_states", "collect_web_content")
# builder.add_edge("initail_states", "collect_github_content")


# builder.add_edge(
#     ["collect_web_content", "collect_github_content"],
#     "process_sources",
# )

# builder.add_edge("process_sources", "filter_topics")
# builder.add_edge("filter_topics", "review_topics")

# builder.add_conditional_edges(
#     "review_topics",
#     route_after_review,
#     {
#         "selected": END,
#         "retry": "initail_states",
#     },
# )


checkpointer = get_checkpointer()

graph = builder.compile(checkpointer=checkpointer)
