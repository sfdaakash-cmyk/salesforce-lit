"""Gradio UI for Salesforce LIT."""

from __future__ import annotations

from collections.abc import Iterator
from queue import Queue
from threading import Thread
from typing import Any

import gradio as gr
from gradio.themes import Base, colors

from .mcp_client import McpClientError
from .pdf_export import create_response_pdf
from .service import LitAnswer, SalesforceLitService

RELEASES = ["Latest release", "Winter '27", "Spring '26", "Winter '26", "Summer '25"]
DOCUMENT_BROWSE_QUERY = "Salesforce documentation"

DARK_THEME = Base(
	primary_hue=colors.emerald,
	neutral_hue=colors.slate,
).set(
	body_background_fill="#090e17",
	body_background_fill_dark="#090e17",
	body_text_color="#e7edf5",
	body_text_color_dark="#e7edf5",
	body_text_color_subdued="#93a4b8",
	body_text_color_subdued_dark="#93a4b8",
	background_fill_primary="#111a27",
	background_fill_primary_dark="#111a27",
	background_fill_secondary="#0c1420",
	background_fill_secondary_dark="#0c1420",
	border_color_primary="#26364a",
	border_color_primary_dark="#26364a",
	color_accent="#36d6a5",
	color_accent_soft="#123c36",
	color_accent_soft_dark="#123c36",
	link_text_color="#36d6a5",
	link_text_color_dark="#36d6a5",
	block_background_fill="#111a27",
	block_background_fill_dark="#111a27",
	block_border_color="#26364a",
	block_border_color_dark="#26364a",
	block_title_text_color="#e7edf5",
	block_title_text_color_dark="#e7edf5",
	panel_background_fill="#111a27",
	panel_background_fill_dark="#111a27",
	panel_border_color="#26364a",
	panel_border_color_dark="#26364a",
	input_background_fill="#0c1420",
	input_background_fill_dark="#0c1420",
	input_background_fill_focus="#0c1420",
	input_background_fill_focus_dark="#0c1420",
	input_border_color="#26364a",
	input_border_color_dark="#26364a",
	input_border_color_focus="#36d6a5",
	input_border_color_focus_dark="#36d6a5",
	input_placeholder_color="#71839a",
	input_placeholder_color_dark="#71839a",
	button_primary_background_fill="#36d6a5",
	button_primary_background_fill_dark="#36d6a5",
	button_primary_background_fill_hover="#54e5bb",
	button_primary_background_fill_hover_dark="#54e5bb",
	button_primary_text_color="#062019",
	button_primary_text_color_dark="#062019",
	button_secondary_background_fill="#172334",
	button_secondary_background_fill_dark="#172334",
	button_secondary_background_fill_hover="#203148",
	button_secondary_background_fill_hover_dark="#203148",
	button_secondary_text_color="#e7edf5",
	button_secondary_text_color_dark="#e7edf5",
)


def create_app(
	chat_service: SalesforceLitService | None = None,
	workspace_service: SalesforceLitService | None = None,
) -> gr.Blocks:
	"""Build the workspace with independent chat and document services."""

	chat_service = chat_service or SalesforceLitService()
	workspace_service = workspace_service or SalesforceLitService()
	try:
		_, initial_collections = workspace_service.knowledge()
	except McpClientError:
		initial_collections = []
	initial_collection_names = [item.name for item in initial_collections]

	def load_documents(release: str, collections: list[str] | None) -> tuple[Any, Any]:
		documents = workspace_service.search_documents(
			DOCUMENT_BROWSE_QUERY, release, collections or None
		)
		choices = [(document.title, document.document_id) for document in documents]
		return (
			gr.update(choices=choices, value=None),
			gr.update(value="Select a document to read its fetched article.", visible=False),
		)

	def refresh_everything(
		release: str, selected_collection: list[str] | None
	) -> tuple[Any, Any, str, Any, list[str]]:
		_, collections = workspace_service.knowledge()
		collection_choices = [item.name for item in collections]
		collection = [
			name for name in (selected_collection or []) if name in collection_choices
		]
		document_update, article_update = load_documents(release, collection or None)
		return (
			gr.update(choices=collection_choices, value=collection),
			document_update,
			f"{len(collection_choices)} collection(s) available",
			article_update,
			collection_choices,
		)

	def fetch_document(document_id: str | None) -> tuple[Any, str]:
		document = workspace_service.fetch_document(document_id or "")
		if not document:
			return gr.update(value="Select a document above to fetch its original content.", visible=False), ""
		link = f"\n\n[Open source]({document.url})" if document.url else ""
		return gr.update(value=f"## {document.title}\n\n{document.excerpt}{link}", visible=True), document.excerpt

	def chat_answer(
		question: str,
		history: list[dict[str, str]] | None,
		release: str,
		collections: list[str] | None,
		reading_context: str,
		available_collections: list[str],
	) -> Iterator[tuple[str, Any]]:
		if not question.strip():
			return

		tokens: Queue[str | None] = Queue()
		results: list[LitAnswer] = []
		failures: list[Exception] = []

		def answer_in_background() -> None:
			try:
				results.append(
					chat_service.answer(
						question,
						release,
						history or [],
						collections or None,
						reading_context,
						available_collections,
						on_token=tokens.put,
					)
				)
			except Exception as exc:
				failures.append(exc)
			finally:
				tokens.put(None)

		worker = Thread(target=answer_in_background, daemon=True)
		worker.start()
		yield "", gr.update(value=None, interactive=False)

		answer = ""
		while True:
			token = tokens.get()
			if token is None:
				break
			answer += token
			yield answer, gr.skip()

		worker.join()
		if failures:
			raise failures[0]
		result = results[0]
		pdf_path = create_response_pdf(result.answer, result.sources)
		yield result.answer, gr.update(value=pdf_path, interactive=True)

	with gr.Blocks(title="Salesforce LIT") as demo:
		gr.Markdown("# Salesforce LIT\nDocumentation workspace for Salesforce developers")
		with gr.Row(equal_height=False):
			with gr.Column(scale=1, min_width=240):
				gr.Markdown("## Controls")
				release = gr.Dropdown(RELEASES, value=RELEASES[0], show_label=False)
				collection_status = gr.Markdown(f"{len(initial_collections)} collection(s) available")
				with gr.Row():
					collection = gr.Dropdown(
						initial_collection_names,
						multiselect=True,
						allow_custom_value=False,
						show_label=False,
						scale=4,
					)
				document = gr.Dropdown([], show_label=False)
				refresh = gr.Button("↻", variant="secondary", size="sm")
				pdf_download = gr.DownloadButton(
					"Download response PDF", value=None, interactive=False
				)
			with gr.Column(scale=3):
				with gr.Column(visible=True) as reading_panel:
					with gr.Row():
						gr.Markdown("## Reading")
						show_chat = gr.Button("💬", variant="secondary", size="sm")
					article = gr.Markdown("Select a document from Controls to fetch its original content.", visible=False)
				with gr.Column(visible=False) as chat_panel:
					with gr.Row():
						gr.Markdown("## Chat")
						close_chat = gr.Button("×", variant="secondary", size="sm")
					reading_context = gr.State("")
					collection_catalog = gr.State(initial_collection_names)
					chat_interface = gr.ChatInterface(
						fn=chat_answer,
						additional_inputs=[release, collection, reading_context, collection_catalog],
						additional_outputs=[pdf_download],
						textbox=gr.Textbox(
							show_label=False,
							placeholder="Ask a Salesforce question...",
							lines=3,
							submit_btn="Submit",
						),
						stop_btn=True,
						show_progress="minimal",
					)

		refresh.click(
			refresh_everything,
			inputs=[release, collection],
			outputs=[collection, document, collection_status, article, collection_catalog],
		)
		release.change(
			refresh_everything,
			inputs=[release, collection],
			outputs=[collection, document, collection_status, article, collection_catalog],
		)
		collection.change(
			load_documents,
			inputs=[release, collection],
			outputs=[document, article],
		)
		document.change(fetch_document, inputs=document, outputs=[article, reading_context])
		show_chat.click(
			lambda: (gr.update(visible=False), gr.update(visible=True)),
			outputs=[reading_panel, chat_panel],
		)
		close_chat.click(
			lambda: (gr.update(visible=True), gr.update(visible=False)),
			outputs=[reading_panel, chat_panel],
		)

	return demo


def launch() -> None:
	create_app().launch(inbrowser=True, theme=DARK_THEME)


__all__ = ["create_app", "launch"]
