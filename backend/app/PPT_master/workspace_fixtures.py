"""Built-in structured workspace definitions."""

def get_builtin_workspace_definition(canvas: str) -> dict:
    """Get builtin workspace definition for canvas format.
    
    Returns workspace structure with:
    - name: Display name
    - theme: Colors and fonts
    - masters: List of master slide definitions
    - layouts: List of layout definitions with kinds
    - placeholders: Placeholder definitions for each layout
    """
    if canvas == "ppt169":
        return {
            "name": "Built-in PPT 16:9 Structured",
            "theme": {
                "colors": ["#1F4788", "#FFFFFF", "#F0F0F0", "#333333"],
                "fonts": {"title": "Arial", "body": "Arial"}
            },
            "masters": [
                {
                    "master_id": "master_default",
                    "name": "Default Master",
                    "background_color": "#FFFFFF"
                }
            ],
            "layouts": [
                {
                    "layout_id": "layout_title",
                    "master_id": "master_default",
                    "kind": "title",
                    "name": "Title Slide"
                },
                {
                    "layout_id": "layout_title_content",
                    "master_id": "master_default",
                    "kind": "title_content",
                    "name": "Title and Content"
                },
                {
                    "layout_id": "layout_image_text",
                    "master_id": "master_default",
                    "kind": "image_text",
                    "name": "Image with Text"
                },
                {
                    "layout_id": "layout_data",
                    "master_id": "master_default",
                    "kind": "data",
                    "name": "Data Visualization"
                },
                {
                    "layout_id": "layout_section",
                    "master_id": "master_default",
                    "kind": "section",
                    "name": "Section Header"
                },
                {
                    "layout_id": "layout_two_column",
                    "master_id": "master_default",
                    "kind": "two_column",
                    "name": "Two Column"
                },
                {
                    "layout_id": "layout_blank",
                    "master_id": "master_default",
                    "kind": "blank",
                    "name": "Blank"
                }
            ],
            "placeholders": [
                {"ph_id": "ph_title_1", "layout_id": "layout_title", "type": "title", "idx": 0},
                {"ph_id": "ph_subtitle_1", "layout_id": "layout_title", "type": "subtitle", "idx": 1},
                {"ph_id": "ph_title_2", "layout_id": "layout_title_content", "type": "title", "idx": 0},
                {"ph_id": "ph_body_2", "layout_id": "layout_title_content", "type": "body", "idx": 1},
                {"ph_id": "ph_title_3", "layout_id": "layout_section", "type": "title", "idx": 0},
                {"ph_id": "ph_title_4", "layout_id": "layout_two_column", "type": "title", "idx": 0},
                {"ph_id": "ph_body_4_left", "layout_id": "layout_two_column", "type": "body", "idx": 1},
                {"ph_id": "ph_body_4_right", "layout_id": "layout_two_column", "type": "body", "idx": 2},
                {"ph_id": "ph_title_5", "layout_id": "layout_image_text", "type": "title", "idx": 0},
                {"ph_id": "ph_image_5", "layout_id": "layout_image_text", "type": "picture", "idx": 1},
                {"ph_id": "ph_body_5", "layout_id": "layout_image_text", "type": "body", "idx": 2},
                {"ph_id": "ph_title_6", "layout_id": "layout_data", "type": "title", "idx": 0},
                {"ph_id": "ph_chart_6", "layout_id": "layout_data", "type": "chart", "idx": 1},
            ]
        }
    raise ValueError(f"Unknown canvas: {canvas}")
