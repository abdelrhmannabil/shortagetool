from __future__ import annotations

import json
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from functions import (
    calculate_required_amount,
    transform_shortage_data,
)


FREQUENT_SHORTAGE_DIR = Path(__file__).resolve().parent / "frequent shortage"
FREQUENT_SHORTAGE_FILE = FREQUENT_SHORTAGE_DIR / "frequent_shortages.json"


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Convert a DataFrame to Excel bytes for download."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="data")
    output.seek(0)
    return output.getvalue()


def normalize_product_name(value: object) -> str:
    """Normalize product names for consistent shortage matching."""
    return " ".join(str(value).strip().lower().split())


def make_json_safe(value: object) -> object:
    """Convert pandas/numpy values into JSON-safe Python values."""
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def load_frequent_shortages() -> list[dict]:
    """Load saved frequent shortage items from JSON."""
    if not FREQUENT_SHORTAGE_FILE.exists():
        return []

    with FREQUENT_SHORTAGE_FILE.open("r", encoding="utf-8") as json_file:
        data = json.load(json_file)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("items", [])
    return []


def save_frequent_shortages(items: list[dict]) -> None:
    """Save frequent shortage items to the app folder."""
    FREQUENT_SHORTAGE_DIR.mkdir(exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
    }
    with FREQUENT_SHORTAGE_FILE.open("w", encoding="utf-8") as json_file:
        json.dump(payload, json_file, ensure_ascii=False, indent=2)


def frequent_shortage_keys(items: list[dict]) -> set[str]:
    """Return normalized product names for saved shortage items."""
    return {
        normalize_product_name(item.get("product_name"))
        for item in items
        if item.get("product_name")
    }


def update_frequent_shortages(
    edited_df: pd.DataFrame, previous_df: pd.DataFrame
) -> int:
    """Persist newly selected shortage rows and return number of new records."""
    saved_items = load_frequent_shortages()
    saved_by_key = {
        normalize_product_name(item.get("product_name")): item
        for item in saved_items
        if item.get("product_name")
    }
    now = datetime.now().isoformat(timespec="seconds")
    added_count = 0
    changed_count = 0

    for row_id, edited_row in edited_df.iterrows():
        is_shortage = bool(edited_row.get("Shortage", False))
        was_shortage = (
            bool(previous_df.loc[row_id, "Shortage"]) if row_id in previous_df.index else False
        )
        if not is_shortage or was_shortage:
            continue

        product_name = edited_row.get("Product Name")
        product_key = normalize_product_name(product_name)
        if not product_key:
            continue

        existing_item = saved_by_key.get(product_key)
        if existing_item:
            existing_item["times_marked"] = int(existing_item.get("times_marked", 1)) + 1
            existing_item["last_marked_at"] = now
            changed_count += 1
            continue

        saved_by_key[product_key] = {
            "product_name": make_json_safe(product_name),
            "category": make_json_safe(edited_row.get("Category")),
            "sale_price": make_json_safe(edited_row.get("Sale Price")),
            "cost": make_json_safe(edited_row.get("Cost")),
            "current_stock": make_json_safe(edited_row.get("Current Stock")),
            "monthly_sold_amount": make_json_safe(edited_row.get("Monthly Sold Amount")),
            "rate": make_json_safe(edited_row.get("Rate")),
            "required_amount": make_json_safe(edited_row.get("Required Amount")),
            "times_marked": 1,
            "first_marked_at": now,
            "last_marked_at": now,
        }
        added_count += 1
        changed_count += 1

    if changed_count:
        sorted_items = sorted(
            saved_by_key.values(),
            key=lambda item: str(item.get("product_name", "")).lower(),
        )
        save_frequent_shortages(sorted_items)

    return added_count


def remove_available_frequent_shortages(current_df: pd.DataFrame) -> int:
    """Remove saved shortage items when current stock is available again."""
    saved_items = load_frequent_shortages()
    if not saved_items:
        return 0

    available_product_names = {
        normalize_product_name(row["Product Name"])
        for _, row in current_df.iterrows()
        if pd.notna(row.get("Product Name"))
        and pd.notna(row.get("Current Stock"))
        and row.get("Current Stock") >= 1
    }
    if not available_product_names:
        return 0

    remaining_items = [
        item
        for item in saved_items
        if normalize_product_name(item.get("product_name")) not in available_product_names
    ]
    removed_count = len(saved_items) - len(remaining_items)
    if removed_count:
        save_frequent_shortages(remaining_items)

    return removed_count


def inject_data_editor_crosshair_highlight(column_count: int) -> None:
    """Add row/column highlight overlay for the active Streamlit data editor cell."""
    components.html(
        f"""
        <script>
        (() => {{
            const columnCount = {column_count};
            const highlightColor = "rgba(173, 216, 230, 0.36)";
            const activeCellColor = "rgba(30, 144, 255, 0.18)";
            const headerHeight = 36;
            const rowHeight = 35;
            const state = window.parent.__shortageEditorCrosshair || {{
                row: 0,
                col: 0,
                pointerX: null,
                pointerY: null,
                container: null,
                canvas: null,
                rowOverlay: null,
                columnOverlay: null,
                cellOverlay: null,
            }};
            window.parent.__shortageEditorCrosshair = state;

            const makeOverlay = (name, color) => {{
                const overlay = window.parent.document.createElement("div");
                overlay.dataset.shortageCrosshair = name;
                overlay.style.position = "absolute";
                overlay.style.pointerEvents = "none";
                overlay.style.background = color;
                overlay.style.zIndex = "5";
                overlay.style.display = "none";
                overlay.style.borderRadius = "3px";
                return overlay;
            }};

            const getEditor = () => {{
                const editors = window.parent.document.querySelectorAll(
                    '[data-testid="stDataFrame"]'
                );
                return editors.length ? editors[editors.length - 1] : null;
            }};

            const ensureOverlay = () => {{
                const container = getEditor();
                const canvas = container ? container.querySelector("canvas") : null;
                if (!container || !canvas) return false;

                if (state.container !== container || state.canvas !== canvas) {{
                    state.container = container;
                    state.canvas = canvas;
                    container.style.position = "relative";
                    container.style.overflow = "hidden";

                    container
                        .querySelectorAll("[data-shortage-crosshair]")
                        .forEach((node) => node.remove());

                    state.rowOverlay = makeOverlay("row", highlightColor);
                    state.columnOverlay = makeOverlay("column", highlightColor);
                    state.cellOverlay = makeOverlay("cell", activeCellColor);
                    container.appendChild(state.rowOverlay);
                    container.appendChild(state.columnOverlay);
                    container.appendChild(state.cellOverlay);
                }}
                return true;
            }};

            const maxRows = () => {{
                if (!state.canvas) return 0;
                const rect = state.canvas.getBoundingClientRect();
                return Math.max(0, Math.floor((rect.height - headerHeight) / rowHeight) - 1);
            }};

            const setFromPoint = (clientX, clientY) => {{
                if (!ensureOverlay()) return;
                const rect = state.canvas.getBoundingClientRect();
                if (
                    clientX < rect.left ||
                    clientX > rect.right ||
                    clientY < rect.top + headerHeight ||
                    clientY > rect.bottom
                ) {{
                    return;
                }}

                const columnWidth = rect.width / columnCount;
                state.col = Math.max(
                    0,
                    Math.min(columnCount - 1, Math.floor((clientX - rect.left) / columnWidth))
                );
                state.row = Math.max(
                    0,
                    Math.min(maxRows(), Math.floor((clientY - rect.top - headerHeight) / rowHeight))
                );
                draw();
            }};

            const draw = () => {{
                if (!ensureOverlay()) return;
                const containerRect = state.container.getBoundingClientRect();
                const canvasRect = state.canvas.getBoundingClientRect();
                const top = canvasRect.top - containerRect.top;
                const left = canvasRect.left - containerRect.left;
                const columnWidth = canvasRect.width / columnCount;
                const rowTop = top + headerHeight + state.row * rowHeight;
                const columnLeft = left + state.col * columnWidth;
                const bodyHeight = Math.max(0, canvasRect.height - headerHeight);

                Object.assign(state.rowOverlay.style, {{
                    display: "block",
                    left: `${{left}}px`,
                    top: `${{rowTop}}px`,
                    width: `${{canvasRect.width}}px`,
                    height: `${{rowHeight}}px`,
                }});
                Object.assign(state.columnOverlay.style, {{
                    display: "block",
                    left: `${{columnLeft}}px`,
                    top: `${{top + headerHeight}}px`,
                    width: `${{columnWidth}}px`,
                    height: `${{bodyHeight}}px`,
                }});
                Object.assign(state.cellOverlay.style, {{
                    display: "block",
                    left: `${{columnLeft}}px`,
                    top: `${{rowTop}}px`,
                    width: `${{columnWidth}}px`,
                    height: `${{rowHeight}}px`,
                    outline: "2px solid rgba(30, 144, 255, 0.42)",
                    outlineOffset: "-2px",
                }});
            }};

            const moveByKey = (event) => {{
                if (!ensureOverlay()) return;
                if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) {{
                    return;
                }}

                if (event.key === "ArrowUp") state.row = Math.max(0, state.row - 1);
                if (event.key === "ArrowDown") state.row = Math.min(maxRows(), state.row + 1);
                if (event.key === "ArrowLeft") state.col = Math.max(0, state.col - 1);
                if (event.key === "ArrowRight") state.col = Math.min(columnCount - 1, state.col + 1);
                window.parent.requestAnimationFrame(draw);
            }};

            if (!state.listenersAttached) {{
                window.parent.document.addEventListener(
                    "pointerdown",
                    (event) => {{
                        state.pointerX = event.clientX;
                        state.pointerY = event.clientY;
                        setFromPoint(event.clientX, event.clientY);
                    }},
                    true
                );
                window.parent.document.addEventListener("keydown", moveByKey, true);
                window.parent.addEventListener("resize", draw);
                state.listenersAttached = true;
            }}

            ensureOverlay();
            if (state.pointerX !== null && state.pointerY !== null) {{
                setFromPoint(state.pointerX, state.pointerY);
            }} else {{
                draw();
            }}
            window.parent.requestAnimationFrame(draw);
            window.parent.setTimeout(draw, 250);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def build_processed_dataframe(
    uploaded_file, start_date, end_date, target_rate: float
) -> pd.DataFrame:
    """Load, transform, and enrich the uploaded shortage data."""
    raw_df = pd.read_excel(uploaded_file, header=None)
    transformed_df = transform_shortage_data(raw_df, start_date, end_date).copy()

    transformed_df["Required Amount"] = transformed_df.apply(
        lambda row: calculate_required_amount(
            current_stock=row["Current Stock"],
            monthly_sold_amount=row["Monthly Sold Amount"],
            target_rate=target_rate,
        )
        if pd.notna(row["Current Stock"]) and pd.notna(row["Monthly Sold Amount"])
        else pd.NA,
        axis=1,
    )
    transformed_df["Ordered Qty"] = 0.0
    transformed_df["Not Found"] = False
    transformed_df["Shortage"] = False
    transformed_df["Row ID"] = transformed_df.index

    return transformed_df


def apply_filters(
    df: pd.DataFrame,
    selected_categories,
    stock_range,
    rate_range,
    hide_zero_required: bool,
) -> pd.DataFrame:
    """Filter dataframe using selected category, stock range, and rate range."""
    filtered_df = df.copy()

    if selected_categories:
        filtered_df = filtered_df[filtered_df["Category"].isin(selected_categories)]

    filtered_df = filtered_df[
        (filtered_df["Current Stock"] >= stock_range[0])
        & (filtered_df["Current Stock"] <= stock_range[1])
    ]
    filtered_df = filtered_df[
        (filtered_df["Rate"].fillna(0) >= rate_range[0])
        & (filtered_df["Rate"].fillna(0) <= rate_range[1])
    ]

    if hide_zero_required:
        filtered_df = filtered_df[filtered_df["Required Amount"].fillna(0) > 0]

    return filtered_df


def apply_search_filter(df: pd.DataFrame, search_text: str) -> pd.DataFrame:
    """Filter rows by partial product name, sale price, or cost matches."""
    search_terms = [term.lower() for term in search_text.split() if term.strip()]
    if not search_terms:
        return df

    searchable_text = (
        df["Product Name"].fillna("").astype(str)
        + " "
        + df["Sale Price"].fillna("").astype(str)
        + " "
        + df["Cost"].fillna("").astype(str)
    ).str.lower()

    search_mask = pd.Series(True, index=df.index)
    for term in search_terms:
        search_mask &= searchable_text.str.contains(term, regex=False, na=False)

    return df[search_mask]


def main() -> None:
    st.set_page_config(page_title="Pharmacy Shortage Tool", layout="wide")
    st.title("Pharmacy Shortage Tool")

    st.markdown("### Inputs")
    top_col_1, top_col_2, top_col_3 = st.columns(3)

    with top_col_1:
        start_date = st.date_input("Start Date")
    with top_col_2:
        end_date = st.date_input("End Date")
    with top_col_3:
        target_rate = st.number_input(
            "Target Rate (Required)",
            min_value=0.0,
            value=0.5,
            step=0.1,
            help="Suggested required amount will target this rate.",
        )

    uploaded_file = st.file_uploader(
        "Upload shortage Excel file", type=["xlsx", "xls", "xlsm", "xlsb"]
    )

    if not uploaded_file:
        st.info("Upload an Excel file to start.")
        return

    if end_date < start_date:
        st.error("End Date must be after or equal to Start Date.")
        return

    state_ready = (
        "data" in st.session_state
        and "source_name" in st.session_state
        and "start_date" in st.session_state
        and "end_date" in st.session_state
        and "target_rate" in st.session_state
    )

    should_rebuild = (
        not state_ready
        or st.session_state["source_name"] != uploaded_file.name
        or st.session_state["start_date"] != start_date
        or st.session_state["end_date"] != end_date
        or st.session_state["target_rate"] != target_rate
    )

    if should_rebuild:
        try:
            st.session_state["data"] = build_processed_dataframe(
                uploaded_file=uploaded_file,
                start_date=start_date,
                end_date=end_date,
                target_rate=target_rate,
            )
            st.session_state["source_name"] = uploaded_file.name
            st.session_state["start_date"] = start_date
            st.session_state["end_date"] = end_date
            st.session_state["target_rate"] = target_rate
        except Exception as exc:  # pragma: no cover
            st.error(f"Error while processing file: {exc}")
            return

    full_df = st.session_state["data"].copy()
    removed_available_shortages = remove_available_frequent_shortages(full_df)
    if removed_available_shortages:
        st.info(
            f"Removed {removed_available_shortages} item(s) from frequent shortages "
            "because current stock is now 1 or more."
        )

    st.markdown("### Filters")
    search_text = st.text_input(
        "Search by item name or price",
        placeholder="Type part of the item name, price, or multiple words",
    )
    filter_col_1, filter_col_2, filter_col_3 = st.columns(3)

    with filter_col_1:
        all_categories = sorted(
            [category for category in full_df["Category"].dropna().unique().tolist()]
        )
        selected_categories = st.multiselect(
            "Category (multi-select)",
            options=all_categories,
            default=all_categories,
        )

    with filter_col_2:
        stock_min_bound = float(full_df["Current Stock"].min(skipna=True))
        stock_max_bound = float(full_df["Current Stock"].max(skipna=True))
        st.markdown("**Current Stock Range**")
        stock_input_col_1, stock_input_col_2 = st.columns(2)
        with stock_input_col_1:
            stock_min_input = st.number_input(
                "Min Stock",
                min_value=stock_min_bound,
                max_value=stock_max_bound,
                value=stock_min_bound,
                step=0.1,
            )
        with stock_input_col_2:
            stock_max_input = st.number_input(
                "Max Stock",
                min_value=stock_min_bound,
                max_value=stock_max_bound,
                value=stock_max_bound,
                step=0.1,
            )
        stock_range = (
            min(stock_min_input, stock_max_input),
            max(stock_min_input, stock_max_input),
        )

    with filter_col_3:
        rate_series = full_df["Rate"].fillna(0)
        rate_min_bound = float(rate_series.min(skipna=True))
        rate_max_bound = float(rate_series.max(skipna=True))
        st.markdown("**Rate Range**")
        rate_input_col_1, rate_input_col_2 = st.columns(2)
        with rate_input_col_1:
            rate_min_input = st.number_input(
                "Min Rate",
                min_value=rate_min_bound,
                max_value=rate_max_bound,
                value=rate_min_bound,
                step=0.1,
            )
        with rate_input_col_2:
            rate_max_input = st.number_input(
                "Max Rate",
                min_value=rate_min_bound,
                max_value=rate_max_bound,
                value=rate_max_bound,
                step=0.1,
            )
        rate_range = (
            min(rate_min_input, rate_max_input),
            max(rate_min_input, rate_max_input),
        )
        hide_zero_required = st.checkbox(
            "Hide items with Required Amount = 0",
            value=False,
        )

    filtered_df = apply_filters(
        df=full_df,
        selected_categories=selected_categories,
        stock_range=stock_range,
        rate_range=rate_range,
        hide_zero_required=hide_zero_required,
    )
    filtered_df = apply_search_filter(filtered_df, search_text)

    frequent_shortage_items = load_frequent_shortages()
    frequent_shortage_product_names = frequent_shortage_keys(frequent_shortage_items)
    hide_frequent_shortages = st.checkbox(
        "Filter items frequently marked as shortage",
        value=True,
    )
    if hide_frequent_shortages and frequent_shortage_product_names:
        filtered_df = filtered_df[
            ~filtered_df["Product Name"]
            .apply(normalize_product_name)
            .isin(frequent_shortage_product_names)
        ]

    st.markdown("### Editable Table")
    visible_columns = [
        "Product Name",
        "Sale Price",
        "Cost",
        "Category",
        "Current Stock",
        "Total Sold Amount",
        "Monthly Sold Amount",
        "Rate",
        "Required Amount",
        "Ordered Qty",
        "Not Found",
        "Shortage",
    ]

    table_tab, shortages_tab = st.tabs(["Editable Table", "shortages"])

    with table_tab:
        editable_df = filtered_df[visible_columns + ["Row ID"]].set_index("Row ID")

        with st.form("editable_table_form"):
            edited_df = st.data_editor(
                editable_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Ordered Qty": st.column_config.NumberColumn(
                        "Ordered Qty", min_value=0.0, step=1.0
                    ),
                    "Not Found": st.column_config.CheckboxColumn("Not Found"),
                    "Shortage": st.column_config.CheckboxColumn("Shortage"),
                },
                disabled=[
                    "Product Name",
                    "Sale Price",
                    "Cost",
                    "Category",
                    "Current Stock",
                    "Total Sold Amount",
                    "Monthly Sold Amount",
                    "Rate",
                    "Required Amount",
                ],
                key="shortage_editor",
            )
            apply_table_changes = st.form_submit_button("Apply Table Changes")

        inject_data_editor_crosshair_highlight(column_count=len(visible_columns))

        if apply_table_changes:
            added_shortages = update_frequent_shortages(
                edited_df=edited_df,
                previous_df=st.session_state["data"],
            )
            st.session_state["data"].loc[edited_df.index, "Ordered Qty"] = edited_df[
                "Ordered Qty"
            ]
            st.session_state["data"].loc[edited_df.index, "Not Found"] = edited_df[
                "Not Found"
            ]
            st.session_state["data"].loc[edited_df.index, "Shortage"] = edited_df[
                "Shortage"
            ]
            if added_shortages:
                st.success(
                    f"Table changes applied. Saved {added_shortages} shortage item(s)."
                )
            else:
                st.success("Table changes applied.")

    with shortages_tab:
        latest_shortage_items = load_frequent_shortages()
        if latest_shortage_items:
            shortages_view_df = pd.DataFrame(latest_shortage_items)
            st.dataframe(shortages_view_df, use_container_width=True, hide_index=True)
            st.caption(f"Saved to: {FREQUENT_SHORTAGE_FILE}")
        else:
            st.info("No frequent shortage items saved yet.")

    st.markdown("### Downloads")
    latest_df = st.session_state["data"].copy()
    ordered_df = latest_df[latest_df["Ordered Qty"] > 0].copy()
    not_found_df = latest_df[latest_df["Not Found"]].copy()
    shortage_df = latest_df[latest_df["Shortage"]].copy()

    download_col_1, download_col_2, download_col_3 = st.columns(3)

    with download_col_1:
        st.download_button(
            label="Download What Is Ordered",
            data=dataframe_to_excel_bytes(ordered_df),
            file_name="what_is_ordered.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with download_col_2:
        st.download_button(
            label="Download What Is Not Found",
            data=dataframe_to_excel_bytes(not_found_df),
            file_name="what_is_not_found.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with download_col_3:
        st.download_button(
            label="Download What Is Shortage",
            data=dataframe_to_excel_bytes(shortage_df),
            file_name="what_is_shortage.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.caption(
        f"Filtered rows: {len(filtered_df)} | Ordered: {len(ordered_df)} | "
        f"Not Found: {len(not_found_df)} | Shortage: {len(shortage_df)}"
    )


if __name__ == "__main__":
    main()
