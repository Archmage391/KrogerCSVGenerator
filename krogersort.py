import pdfminer
import pdfplumber
import csv
import re
import os
import sys
from datetime import datetime

# ----------------------------
# Regex patterns
# ----------------------------
item_desc_pattern = re.compile(r"^(.+?)\s+\$?(\d+\.\d{2})$")
qty_price_pattern = re.compile(r"^(\d+)\s+x\s+\$?(\d+\.\d{2})(?:\s+\$?(\d+\.\d{2}))?\s+each")
weight_price_pattern = re.compile(r"^([\d\.]+)\s*(?:lb|lbs|oz|ct)\s+x\s+\$?(\d+\.\d{2})\s+each.*$")
coupon_pattern = re.compile(r"^Item Coupon/Sale:\s+\$(-\d+\.\d{2})$")
upc_pattern = re.compile(r"^UPC:\s+(\d+)$")
subtotal_pattern = re.compile(r"^Original Item Total\s+\$(\d+\.\d{2})$")
tax_pattern = re.compile(r"^Sales Tax\s+\+\$(\d+\.\d{2})$")
total_pattern = re.compile(r"^Order Total\s+\$(\d+\.\d{2})$")
date_pattern = re.compile(r"^Order Date:\s+(\w+\. \d{1,2}, \d{4})$")
payment_details_pattern = re.compile(r"(MASTERCARD|VISA|DISCOVER|DEBIT).?(\d{4})")

# Date Format
date_format = "%b. %d, %Y"
date_output_format = "%m-%d-%Y"

# ----------------------------
# Helpers
# ----------------------------
def parse_item_block(lines, receipt_name, receipt_date, payment_details):
    """Parse a block of lines into a structured item entry"""
    item_data = {
        "Receipt": receipt_name,
        "Date": receipt_date,
        "Description": "",
        "PricePaid": "",
        "Qty": "",
        "UnitPrice": "",
        "OriginalUnitPrice": "",
        "Card Used": payment_details
    }

    for line in lines:
        line = line.strip()

        if item_desc_pattern.match(line):
            m = item_desc_pattern.match(line)
            item_data["Description"] = m.group(1).strip()
            item_data["PricePaid"] = m.group(2)

        elif qty_price_pattern.match(line):
            m = qty_price_pattern.match(line)
            item_data["Qty"] = m.group(1)
            item_data["UnitPrice"] = m.group(2)
            item_data["OriginalUnitPrice"] = m.group(3) if m.group(3) else m.group(2)

        elif weight_price_pattern.match(line):
            m = weight_price_pattern.match(line)
            item_data["Qty"] = m.group(1) + " lbs"
            item_data["UnitPrice"] = m.group(2)
            # Extended price sometimes shown as BasePrice
            if not item_data["OriginalUnitPrice"]:
                item_data["OriginalUnitPrice"] = item_data["PricePaid"]

        elif coupon_pattern.match(line):
            m = coupon_pattern.match(line)
            item_data["Discount"] = m.group(1)

    return item_data

def get_payment_details(pdf: pdfplumber.pdf.PDF):
    for page in pdf.pages:
            text = page.extract_text()

            if not text:
                continue

            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                # Try to payment details from header
                if payment_details_pattern.match(line):
                    m = payment_details_pattern.match(line)
                    return m.group(1) + m.group(2)

def parse_kroger_receipt(pdf_path):
    """Parse a single Kroger PDF receipt into structured entries"""
    item_entries = []
    receipt_name = os.path.basename(pdf_path)
    receipt_date = ""

    # Totals outside items
    summary_entry = {
        "Receipt": receipt_name,
        "Date": receipt_date,
        "Card Used": "",
        "SubTotal": "",
        "Taxes": "",
        "Total": ""
    }

    subTotal = 0
    taxes = 0
    total = 0

    with pdfplumber.open(pdf_path) as pdf:
        block = []

        payment_details = get_payment_details(pdf)

        summary_entry["Card Used"] = payment_details

        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue

            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                # Collect item block lines
                block.append(line)
                if upc_pattern.match(line):
                    # Completed one item block
                    item_data = parse_item_block(block, receipt_name, receipt_date, payment_details)
                    item_entries.append(item_data)
                    block = []

                if not receipt_date:
                    if date_pattern.match(line):
                        date_object = datetime.strptime(date_pattern.match(line).group(1), date_format)
                        receipt_date = date_object.strftime(date_output_format)
                        summary_entry["Date"] = receipt_date
                if subTotal == 0:
                    if subtotal_pattern.match(line):
                        amt = subtotal_pattern.match(line).group(1)
                        summary_entry["SubTotal"] = amt
                if taxes == 0:
                    if  tax_pattern.match(line):
                        amt = tax_pattern.match(line).group(1)
                        summary_entry["Taxes"] = amt
                if total == 0:
                    if total_pattern.match(line):
                        amt = total_pattern.match(line).group(1)
                        summary_entry["Total"] = amt


    return [item_entries, summary_entry]

def write_entires_to_file(fileName, fieldnames, entries):
    # Write CSV
    with open(fileName, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames
        )
        writer.writeheader()
        writer.writerows(entries)

        print(f"Saved {len(entries)} entries from receipts into {fileName}")



def parse_files(filePaths: list):
    """Process all Kroger PDFs in a directory into one CSV"""
    item_entries = []
    summary_entries = []

    for filePath in filePaths:
        if filePath.lower().endswith(".pdf"):
            print(f"Parsing {filePath}...")
            combined_entries = parse_kroger_receipt(filePath)
            item_entries.extend(combined_entries[0])
            summary_entries.append(combined_entries[1])

    write_entires_to_file("./itemized.csv", ["Receipt", "Date", "Description", "PricePaid", "Qty",
                        "UnitPrice", "OriginalUnitPrice", "Type", "Card Used"], item_entries)
    write_entires_to_file("./summarized.csv", ["Receipt", "Date", "Card Used", "SubTotal", "Taxes", "Total"], summary_entries)

if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("Missing File Arguments")
        input("Press Enter to exit..")
    else:
        # Remove Self Referential Argument
        sys.argv.pop(0)
        parse_files(sys.argv)
        input("Press Enter to exit..")