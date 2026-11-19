from decimal import Decimal

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
item_coupon_pattern = re.compile(r"^Item Coupons/Sale:\s+\$(-\d+\.\d{2})$")
upc_pattern = re.compile(r"^UPC:\s+(\d+)$")
#subtotal_pattern = re.compile(r"^Original Item Total\s+\$(\d+\.\d{2})$")
#tax_pattern = re.compile(r"^Sales Tax\s+\+\$(\d+\.\d{2})$")
#total_pattern = re.compile(r"^Order Total\s+\$(\d+\.\d{2})$")
date_pattern = re.compile(r"^Order Date:\s+(\w+\. \d{1,2}, \d{4})$")
payment_details_pattern = re.compile(r"(mastercard|visa|discover|debit).?(\d{4})")

# Order Level Regex
order_subtotal_pattern = re.compile(r"^Original Item Total\s+\$(\d+\.\d{2})$")
order_coupon_adjustment_pattern = re.compile(r"^Item Coupons/Sales\s+-\$(\d+\.\d{2})$") # Removes from Subtotal
order_fullfillment_fee_pattern = re.compile(r"^Fulfillment Fee\s+\+\$(\d+\.\d{2})$")
order_sales_tax_pattern = re.compile(r"^Sales Tax\s+\$(\d+\.\d{2})$")
order_total_pattern = re.compile(r"^Order Total\s+\$(\d+\.\d{2})$") # Final Price Paid

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
            item_data["Qty"] = m.group(1)
            item_data["UnitPrice"] = m.group(2)
            # Extended price sometimes shown as BasePrice
            if not item_data["OriginalUnitPrice"]:
                item_data["OriginalUnitPrice"] = item_data["PricePaid"]

        elif item_coupon_pattern.match(line):
            m = item_coupon_pattern.match(line)
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
                if payment_details_pattern.match(line.lower()):
                    m = payment_details_pattern.match(line.lower())
                    return m.group(1).upper() + m.group(2)

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
        "Discount": "",
        "Total": ""
    }

    orderSubTotal = 0
    orderCoupon = 0
    orderFulfillment = 0
    orderTaxes = 0
    orderTotal = 0

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

                if orderSubTotal == 0:
                    if order_subtotal_pattern.match(line):
                        amt = order_subtotal_pattern.match(line).group(1)
                        clean_str = amt.replace("$", "").replace(",", "").strip()
                        orderSubTotal = Decimal(clean_str)
                        summary_entry["SubTotal"] = amt
                        
                if orderCoupon == 0:
                    if order_coupon_adjustment_pattern.match(line):
                        amt = order_coupon_adjustment_pattern.match(line).group(1)
                        clean_str = amt.replace("$", "").replace(",", "").strip()
                        orderCoupon = Decimal(clean_str)
                        summary_entry["Discount"] = amt

                if orderFulfillment == 0:
                    if order_fullfillment_fee_pattern.match(line):
                        amt = order_fullfillment_fee_pattern.match(line).group(1)
                        clean_str = amt.replace("$", "").replace(",", "").strip()
                        orderFulfillment = Decimal(clean_str)

                # if orderTaxes == 0:
                #     if  order_sales_tax_pattern.match(line):
                #         amt = order_sales_tax_pattern.match(line).group(1)
                #         clean_str = amt.replace("$", "").replace(",", "").strip()
                #         orderTaxes = Decimal(clean_str)
                #         summary_entry["Taxes"] = amt

                if orderTotal == 0:
                    if order_total_pattern.match(line):
                        amt = order_total_pattern.match(line).group(1)
                        clean_str = amt.replace("$", "").replace(",", "").strip()
                        orderTotal = Decimal(clean_str)
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

    #write_entires_to_file("./itemized.csv", ["Receipt", "Date", "Description", "PricePaid", "Qty", "UnitPrice", "OriginalUnitPrice", "Type", "Card Used"], item_entries)
    write_entires_to_file("./summarized.csv", ["Receipt", "Date", "Card Used", "SubTotal", "Discount", "Total"], summary_entries)

if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("Missing File Arguments")
        input("Press Enter to exit..")
    else:
        # Remove Self Referential Argument
        sys.argv.pop(0)
        parse_files(sys.argv)
        input("Press Enter to exit..")