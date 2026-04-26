import time
import re
from datetime import datetime

import pytz
import yaml

from utils import (
    back_up_files,
    deduplicate_papers,
    format_arxiv_search_query,
    generate_table,
    get_daily_date,
    get_daily_papers_by_keyword_with_retries,
    get_query_title,
    remove_backups,
    restore_files,
)


CONFIG_PATH = "config.yaml"
REPOSITORY_URL = "https://github.com/quanyushi/DailyArxiv"

# NOTE: arXiv API seems to sometimes return an unexpected empty list.


def load_config(config_path=CONFIG_PATH):
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_last_update_date():
    with open("README.md", "r") as f:
        while True:
            line = f.readline()
            if "Last update:" in line:
                return line.split(": ")[1].strip()
            if line == "":
                return None


def get_query_description(query):
    return query.get("description", "") if isinstance(query, dict) else ""


def get_anchor(title):
    anchor = title.strip().lower()
    anchor = re.sub(r"[^a-z0-9 -]", "", anchor)
    anchor = re.sub(r"\s+", "-", anchor)
    return anchor


def write_readme_header(f_rm, current_date, search_queries, max_result):
    f_rm.write("<div align=\"center\">\n")
    f_rm.write("<h1>DailyArxiv: Off-Road Autonomy Papers</h1>\n")
    f_rm.write("<p><strong>Tracking off-road autonomous driving, unstructured-environment navigation, VLA/VLM planning, and world-model papers.</strong></p>\n")
    f_rm.write("<p>\n")
    f_rm.write("<img alt=\"arXiv\" src=\"https://img.shields.io/badge/source-arXiv-b31b1b\">\n")
    f_rm.write("<img alt=\"Python\" src=\"https://img.shields.io/badge/python-3.10%2B-3776ab\">\n")
    f_rm.write("<img alt=\"GitHub Actions\" src=\"https://img.shields.io/badge/update-GitHub%20Actions-2088ff\">\n")
    f_rm.write("</p>\n")
    f_rm.write("</div>\n\n")
    f_rm.write("## Overview\n")
    f_rm.write(
        "| Item | Value |\n"
        "| --- | --- |\n"
        "| Last update | `{0}` |\n"
        "| Search topics | `{1}` |\n"
        "| Query mode | Title/abstract combined Boolean queries |\n"
        "| Max results per topic | `{2}` |\n"
        "| Duplicate handling | arXiv ID based cross-topic deduplication |\n\n".format(current_date, len(search_queries), max_result)
    )
    f_rm.write("Watch this repository to receive GitHub notifications when the daily paper list is updated.\n\n")
    f_rm.write("## Topics\n")
    for query in search_queries:
        title = get_query_title(query)
        description = get_query_description(query)
        f_rm.write("- [{0}](#{1})".format(title, get_anchor(title)))
        if description:
            f_rm.write(": {0}".format(description))
        f_rm.write("\n")
    f_rm.write("\n")
    f_rm.write("## Papers\n\n")


def write_issue_header(f_is, issues_result):
    f_is.write("---\n")
    f_is.write("title: Latest {0} Papers - {1}\n".format(issues_result, get_daily_date()))
    f_is.write("labels: documentation\n")
    f_is.write("---\n")
    f_is.write(
        "**Please check the [Github]({0}) page for a better reading experience and more papers.**\n\n".format(REPOSITORY_URL)
    )


def main():
    config = load_config()
    search_queries = config["search_queries"]
    max_result = config.get("max_result", 50)
    issues_result = config.get("issues_result", 15)
    column_names = config.get("column_names", ["Title", "Link", "Abstract", "Date", "Comment"])

    # beijing_timezone = pytz.timezone('Asia/Shanghai')
    eastern_timezone = pytz.timezone("US/Eastern")
    current_date = datetime.now(eastern_timezone).strftime("%Y-%m-%d")
    _last_update_date = get_last_update_date()
    # if last_update_date == current_date:
    #     sys.exit("Already updated today!")

    back_up_files() # back up README.md and ISSUE_TEMPLATE.md

    try:
        with open("README.md", "w") as f_rm, open(".github/ISSUE_TEMPLATE.md", "w") as f_is:
            write_readme_header(f_rm, current_date, search_queries, max_result)
            write_issue_header(f_is, issues_result)

            seen_papers = set()
            for query in search_queries:
                title = get_query_title(query)
                description = get_query_description(query)
                f_rm.write("### {0}\n".format(title))
                if description:
                    f_rm.write("> {0}\n\n".format(description))
                f_rm.write("<details><summary>arXiv query</summary><code>{0}</code></details>\n\n".format(format_arxiv_search_query(query)))
                f_is.write("## {0}\n".format(title))

                papers = get_daily_papers_by_keyword_with_retries(query, column_names, max_result)
                papers = deduplicate_papers(papers, seen_papers)
                f_rm.write("**Unique papers shown:** `{0}`\n\n".format(len(papers)))

                rm_table = generate_table(papers)
                is_table = generate_table(papers[:issues_result], ignore_keys=["Abstract"])
                f_rm.write(rm_table)
                f_rm.write("\n\n")
                f_is.write(is_table)
                f_is.write("\n\n")
                time.sleep(5) # avoid being blocked by arXiv API
    except Exception:
        restore_files()
        raise
    else:
        remove_backups()


if __name__ == "__main__":
    main()
