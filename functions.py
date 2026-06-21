from __future__ import annotations

from pathlib import Path
from typing import Union

import pandas as pd


DateInput = Union[str, pd.Timestamp]


def _normalize_text(value: object) -> str:
    """Normalize header text for case-insensitive matching."""
    text = str(value).strip().lower()
    text = " ".join(text.split())
    return text


def _find_header_row(df: pd.DataFrame) -> int:
    """
    Find the row index that contains required header labels.

    Required labels:
    - Product Name
    - Product Ref
    - Sale Price
    - Cost
    """
    required_headers = {"product name", "product ref", "sale price", "cost"}

    for idx in range(len(df)):
        row_values = {_normalize_text(cell) for cell in df.iloc[idx].tolist()}
        if required_headers.issubset(row_values):
            return idx

    raise ValueError(
        "Could not find a valid header row containing Product Name, "
        "Product Ref, Sale Price, and Cost."
    )


def _parse_numeric_value(value: object) -> float:
    """
    Parse numeric values from messy Excel text (currency, commas, spaces).
    """
    if pd.isna(value):
        return pd.NA

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return pd.NA

    # Keep digits and decimal/thousands separators only.
    text = "".join(ch for ch in text if ch.isdigit() or ch in {".", ",", "-"})
    if not text:
        return pd.NA

    # If both separators exist, treat comma as thousands separator.
    if "," in text and "." in text:
        text = text.replace(",", "")
    # If only comma exists, treat it as decimal separator.
    elif "," in text:
        text = text.replace(",", ".")

    number = pd.to_numeric(text, errors="coerce")
    if pd.isna(number):
        return pd.NA
    return float(number)


def calculate_decimal_months(start_date: DateInput, end_date: DateInput) -> float:
    """
    Calculate the period between two dates in decimal months.

    The calculation uses average month length (30.44 days),
    then rounds the result to 1 decimal place.
    """
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    if pd.isna(start) or pd.isna(end):
        raise ValueError("start_date and end_date must be valid dates.")
    if end < start:
        raise ValueError("end_date must be after or equal to start_date.")

    days_between = (end - start).days
    months_decimal = round(days_between / 30.44, 1)
    return months_decimal


def calculate_monthly_sold_amount(quantity_sold: float, decimal_months: float) -> float:
    """
    Calculate monthly sold amount based on total sold quantity and decimal months.
    """
    if decimal_months <= 0:
        raise ValueError("decimal_months must be greater than 0.")

    return quantity_sold / decimal_months


def calculate_stock_rate(current_stock: float, monthly_sold_amount: float) -> float:
    """
    Calculate stock coverage rate by dividing stock by monthly sold amount.
    """
    if monthly_sold_amount <= 0:
        raise ValueError("monthly_sold_amount must be greater than 0.")

    return current_stock / monthly_sold_amount


def calculate_required_amount(
    current_stock: float, monthly_sold_amount: float, target_rate: float
) -> float:
    """
    Calculate extra quantity needed so rate reaches at least target_rate.
    """
    if target_rate < 0:
        raise ValueError("target_rate must be greater than or equal to 0.")
    if monthly_sold_amount < 0:
        raise ValueError("monthly_sold_amount must be greater than or equal to 0.")

    required = (target_rate * monthly_sold_amount) - current_stock
    return max(0.0, required)


def load_excel_file(file_path: Union[str, Path], sheet_name=0) -> pd.DataFrame:
    """
    Load an Excel file from user-provided path and return a DataFrame.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")
    if path.suffix.lower() not in {".xlsx", ".xls", ".xlsm", ".xlsb"}:
        raise ValueError("Unsupported file type. Please provide an Excel file.")

    return pd.read_excel(path, sheet_name=sheet_name)


def transform_shortage_data(
    df: pd.DataFrame, start_date: DateInput, end_date: DateInput
) -> pd.DataFrame:
    """
    Transform raw inventory/sales sheet to the required project format.

    Steps:
    1) Remove upper rows until the real header row is found.
    2) Keep only needed columns.
    3) Rename Total QoH -> Current Stock, Total Sold QTY -> Total Sold Amount.
    4) Calculate Monthly Sold Amount and Rate.
    """
    if df.empty:
        raise ValueError("Input DataFrame is empty.")

    header_row_idx = _find_header_row(df)

    transformed = df.iloc[header_row_idx + 1 :].copy()
    transformed.columns = df.iloc[header_row_idx].tolist()
    transformed = transformed.reset_index(drop=True)

    normalized_to_original = {
        _normalize_text(col): col for col in transformed.columns if pd.notna(col)
    }

    required_column_map = {
        "product name": "Product Name",
        "sale price": "Sale Price",
        "cost": "Cost",
        "category": "Category",
        "total qoh": "Current Stock",
        "total sold qty": "Total Sold Amount",
    }

    missing = [
        src_name
        for src_name in required_column_map
        if src_name not in normalized_to_original
    ]
    if missing:
        raise ValueError(
            "Missing required columns after header detection: " + ", ".join(missing)
        )

    selected_original_columns = [
        normalized_to_original[src_name] for src_name in required_column_map
    ]
    transformed = transformed[selected_original_columns].copy()

    transformed.columns = [required_column_map[src_name] for src_name in required_column_map]

    for numeric_col in ["Sale Price", "Cost", "Current Stock", "Total Sold Amount"]:
        transformed[numeric_col] = transformed[numeric_col].apply(_parse_numeric_value)

    decimal_months = calculate_decimal_months(start_date=start_date, end_date=end_date)
    transformed["Monthly Sold Amount"] = transformed["Total Sold Amount"].apply(
        lambda qty: calculate_monthly_sold_amount(qty, decimal_months)
        if pd.notna(qty)
        else pd.NA
    )

    transformed["Rate"] = transformed.apply(
        lambda row: calculate_stock_rate(row["Current Stock"], row["Monthly Sold Amount"])
        if pd.notna(row["Current Stock"])
        and pd.notna(row["Monthly Sold Amount"])
        and row["Monthly Sold Amount"] > 0
        else pd.NA,
        axis=1,
    )

    return transformed
