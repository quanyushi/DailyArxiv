import os
import re
import time
import pytz
import shutil
import datetime
from typing import Any, Dict, List, Union
import urllib, urllib.request

import feedparser
from easydict import EasyDict


def remove_duplicated_spaces(text: str) -> str:
    return " ".join(text.split())

QuerySpec = Union[str, Dict[str, Any]]


def get_query_title(query: QuerySpec) -> str:
    if isinstance(query, str):
        return query
    return query["title"]


def _quote_term(term: str) -> str:
    return '"' + term.replace('"', '\\"') + '"'


def _title_or_abstract_clause(term: str) -> str:
    term = _quote_term(term)
    return "(ti:{0}+OR+abs:{0})".format(term)


def format_arxiv_search_query(query: QuerySpec, link: str = "OR") -> str:
    if isinstance(query, str):
        assert link in ["OR", "AND"], "link should be 'OR' or 'AND'"
        term = _quote_term(query)
        return "ti:{0} {1} abs:{0}".format(term, link)

    clauses = []
    for group in query["terms"]:
        terms = group if isinstance(group, list) else [group]
        group_clauses = ["ti:{0} OR abs:{0}".format(_quote_term(term)) for term in terms]
        clauses.append("(" + " OR ".join(group_clauses) + ")")
    return " AND ".join(clauses)


def build_arxiv_search_query(query: QuerySpec, link: str = "OR") -> str:
    if isinstance(query, str):
        assert link in ["OR", "AND"], "link should be 'OR' or 'AND'"
        keyword = _quote_term(query)
        return "ti:{0}+{1}+abs:{0}".format(keyword, link)

    clauses = []
    for group in query["terms"]:
        terms = group if isinstance(group, list) else [group]
        group_clauses = [_title_or_abstract_clause(term) for term in terms]
        clauses.append("(" + "+OR+".join(group_clauses) + ")")
    return "+AND+".join(clauses)


def request_paper_with_arXiv_api(query: QuerySpec, max_results: int, link: str = "OR") -> List[Dict[str, str]]:
    search_query = build_arxiv_search_query(query, link)
    url = "http://export.arxiv.org/api/query?search_query={0}&max_results={1}&sortBy=lastUpdatedDate".format(search_query, max_results)
    url = urllib.parse.quote(url, safe="%/:=&?~#+!$,;'@()*[]")
    response = urllib.request.urlopen(url).read().decode('utf-8')
    feed = feedparser.parse(response)

    # NOTE default columns: Title, Authors, Abstract, Link, Tags, Comment, Date
    papers = []
    for entry in feed.entries:
        entry = EasyDict(entry)
        paper = EasyDict()

        # title
        paper.Title = remove_duplicated_spaces(entry.title.replace("\n", " "))
        # abstract
        paper.Abstract = remove_duplicated_spaces(entry.summary.replace("\n", " "))
        # authors
        paper.Authors = [remove_duplicated_spaces(_["name"].replace("\n", " ")) for _ in entry.authors]
        # link
        paper.Link = remove_duplicated_spaces(entry.link.replace("\n", " "))
        # tags
        paper.Tags = [remove_duplicated_spaces(_["term"].replace("\n", " ")) for _ in entry.tags]
        # comment
        paper.Comment = remove_duplicated_spaces(entry.get("arxiv_comment", "").replace("\n", " "))
        # date
        paper.Date = entry.updated

        papers.append(paper)
    return papers

def filter_tags(papers: List[Dict[str, str]], target_fileds: List[str]=["cs", "stat"]) -> List[Dict[str, str]]:
    # filtering tags: only keep the papers in target_fileds
    results = []
    for paper in papers:
        tags = paper.Tags
        for tag in tags:
            if tag.split(".")[0] in target_fileds:
                results.append(paper)
                break
    return results

def get_daily_papers_by_keyword_with_retries(query: QuerySpec, column_names: List[str], max_result: int, link: str = "OR", retries: int = 2) -> List[Dict[str, str]]:
    for _ in range(retries):
        papers = get_daily_papers_by_keyword(query, column_names, max_result, link)
        if len(papers) > 0: return papers
        else:
            print("Unexpected empty list, retrying...")
            time.sleep(60) # wait for 1 minute
    # failed
    return []

def get_daily_papers_by_keyword(query: QuerySpec, column_names: List[str], max_result: int, link: str = "OR") -> List[Dict[str, str]]:
    # get papers
    papers = request_paper_with_arXiv_api(query, max_result, link) # NOTE default columns: Title, Authors, Abstract, Link, Tags, Comment, Date
    # NOTE filtering tags: only keep the papers in cs field
    # TODO filtering more
    papers = filter_tags(papers)
    # select columns for display
    papers = [{column_name: paper[column_name] for column_name in column_names} for paper in papers]
    return papers


def get_paper_identity(paper: Dict[str, str]) -> str:
    link = paper.get("Link", "")
    match = re.search(r"arxiv\.org/abs/([^?#]+)", link)
    if match:
        return re.sub(r"v\d+$", "", match.group(1))
    return link or paper.get("Title", "")


def deduplicate_papers(papers: List[Dict[str, str]], seen_papers: set) -> List[Dict[str, str]]:
    results = []
    for paper in papers:
        paper_identity = get_paper_identity(paper)
        if paper_identity in seen_papers:
            continue
        seen_papers.add(paper_identity)
        results.append(paper)
    return results


def generate_table(papers: List[Dict[str, str]], ignore_keys: List[str] = []) -> str:
    if len(papers) == 0:
        return "_No matching papers found for this query._"

    formatted_papers = []
    keys = papers[0].keys()
    for paper in papers:
        # process fixed columns
        formatted_paper = EasyDict()
        ## Title and Link
        formatted_paper.Title = "**" + "[{0}]({1})".format(paper["Title"], paper["Link"]) + "**"
        ## Process Date (format: 2021-08-01T00:00:00Z -> 2021-08-01)
        formatted_paper.Date = paper["Date"].split("T")[0]
        
        # process other columns
        for key in keys:
            if key in ["Title", "Link", "Date"] or key in ignore_keys:
                continue
            elif key == "Abstract":
                # add show/hide button for abstract
                formatted_paper[key] = "<details><summary>Show</summary><p>{0}</p></details>".format(paper[key])
            elif key == "Authors":
                # NOTE only use the first author
                formatted_paper[key] = paper[key][0] + " et al."
            elif key == "Tags":
                tags = ", ".join(paper[key])
                if len(tags) > 10:
                    formatted_paper[key] = "<details><summary>{0}...</summary><p>{1}</p></details>".format(tags[:5], tags)
                else:
                    formatted_paper[key] = tags
            elif key == "Comment":
                if paper[key] == "":
                    formatted_paper[key] = ""
                elif len(paper[key]) > 20:
                    formatted_paper[key] = "<details><summary>{0}...</summary><p>{1}</p></details>".format(paper[key][:5], paper[key])
                else:
                    formatted_paper[key] = paper[key]
        formatted_papers.append(formatted_paper)

    # generate header
    columns = formatted_papers[0].keys()
    # highlight headers
    columns = ["**" + column + "**" for column in columns]
    header = "| " + " | ".join(columns) + " |"
    header = header + "\n" + "| " + " | ".join(["---"] * len(formatted_papers[0].keys())) + " |"
    # generate the body
    body = ""
    for paper in formatted_papers:
        body += "\n| " + " | ".join(paper.values()) + " |"
    return header + body

def back_up_files():
    # back up README.md and ISSUE_TEMPLATE.md
    shutil.move("README.md", "README.md.bk")
    shutil.move(".github/ISSUE_TEMPLATE.md", ".github/ISSUE_TEMPLATE.md.bk")

def restore_files():
    # restore README.md and ISSUE_TEMPLATE.md
    shutil.move("README.md.bk", "README.md")
    shutil.move(".github/ISSUE_TEMPLATE.md.bk", ".github/ISSUE_TEMPLATE.md")

def remove_backups():
    # remove README.md and ISSUE_TEMPLATE.md
    os.remove("README.md.bk")
    os.remove(".github/ISSUE_TEMPLATE.md.bk")

def get_daily_date():
    # get beijing time in the format of "March 1, 2021"
    # beijing_timezone = pytz.timezone('Asia/Shanghai')
    eastern_timezone = pytz.timezone('US/Eastern')
    today = datetime.datetime.now(eastern_timezone)
    return today.strftime("%B %d, %Y")
