import os, sys
import re
from collections import OrderedDict
from datetime import datetime
import json
try:
    curr_path = os.path.dirname(os.path.abspath(__file__))
    teedoc_project_path = os.path.abspath(os.path.join(curr_path, "..", "..", ".."))
    if os.path.basename(teedoc_project_path) == "teedoc":
        sys.path.insert(0, teedoc_project_path)
except Exception:
    pass
from teedoc import Plugin_Base
from teedoc import Fake_Logger

__version__ = "2.4.0"

class Plugin(Plugin_Base):
    name = "teedoc-plugin-markdown-parser"
    desc = "markdown parser plugin for teedoc"
    defautl_config = {
        "parse_files": ["md"],
        "mathjax": {
            "enable": True,
            "file_name": "tex-mml-chtml", # http://docs.mathjax.org/en/latest/web/components/index.html
            "config": {
                "loader": {
                    "load": ['output/svg']
                },
                "tex": {
                    "inlineMath": [['$', '$'], ['\\(', '\\)']]
                },
                "svg": {
                    "fontCache": 'global'
                }
            }
        }
    }

    def on_init(self, config, doc_src_path, site_config, logger = None, multiprocess = True, **kw_args):
        '''
            @config a dict object
            @logger teedoc.logger.Logger object
        '''
        self.multiprocess = multiprocess
        self.logger = Fake_Logger() if not logger else logger
        self.doc_src_path = doc_src_path
        self.site_config = site_config
        self.config = Plugin.defautl_config
        mathjax_config = self.config["mathjax"]
        if "mathjax" in config:
            for k,v in config["mathjax"].items():
                if type(v) != dict:
                    mathjax_config[k] = v
                else:
                    mathjax_config[k].update(v)
        self.config.update(config)
        self.config["mathjax"] = mathjax_config
        self.logger.i("-- plugin <{}> init".format(self.name))
        self.logger.i("-- plugin <{}> config: {}".format(self.name, self.config))
        if not self.multiprocess:
            from .renderer import create_markdown_parser
            from .parse_metadata import Meta_Parser
            self.create_markdown_parser = create_markdown_parser 
            self.Meta_Parser = Meta_Parser

    def on_new_process_init(self):
        '''
            for multiple processing, for below func, will be called in new process,
            every time create a new process, this func will be invoke
        '''
        from .renderer import create_markdown_parser
        from .parse_metadata import Meta_Parser
        self.md_parser = create_markdown_parser()
        self.meta_parser = Meta_Parser()


    def on_new_process_del(self):
        '''
            for multiple processing, for below func, will be called in new process,
            every time exit a new process, this func will be invoke
        '''
        del self.md_parser
        del self.meta_parser

    def on_parse_files(self, files):
        # result, format must be this
        result = {
            "ok": False,
            "msg": "",
            "htmls": OrderedDict()
        }
        # function parse md file is disabled
        if not "md" in self.config["parse_files"]:
            result["msg"] = "disabled markdown parse, but only support markdown"
            return result
        self.logger.d("-- plugin <{}> parse {} files".format(self.name, len(files)))
        # self.logger.d("files: {}".format(files))
        
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext.endswith("md"):
                with open(file, encoding="utf-8") as f:
                    content = f.read().strip()
                    content = self._update_link(content)
                    try:
                        if not self.multiprocess:
                            md_parser = self.create_markdown_parser()
                            meta_parser = self.Meta_Parser()
                        else:
                            md_parser = self.md_parser
                            meta_parser = self.meta_parser
                        metadata, content_no_meta = meta_parser.parse_meta(content)
                        html = md_parser(content_no_meta)
                    except Exception as e:
                        import io, traceback
                        traceback.print_exc()
                        self.logger.w("parse markdown file {} fail, please check markdown content format".format(file))
                        continue
                    if "title" in metadata:
                        title = metadata["title"]
                    else:
                        title = ""
                    if "keywords" in metadata and not metadata["keywords"].strip() == "":
                        keywords = metadata["keywords"].split(",")
                    else:
                        keywords = []
                    if "tags" in metadata and not metadata["tags"].strip() == "":
                        tags = metadata["tags"].split(",")
                    else:
                        tags = []
                    if "desc" in metadata:
                        desc = metadata["desc"]
                    else:
                        desc = ""
                    date = None
                    ts = int(os.stat(file).st_mtime)
                    if "date" in metadata:
                        date = metadata["date"].strip().lower()
                        # set date to false to disable date display
                        if date and (date == "false" or date == "none"):
                            date = ""
                        else:
                            GMT_FORMAT = '%Y-%m-%d'
                            try:
                                date_obj = datetime.strptime(date, GMT_FORMAT)
                                ts = int(date_obj.timestamp())
                            except Exception as e:
                                pass
                    if "author" in metadata:
                        author = metadata["author"]
                    else:
                        author = ""
                    result["htmls"][file] = {
                        "title": title,
                        "desc": desc,
                        "keywords": keywords,
                        "tags": tags,
                        "body": html,
                        "date": date,
                        "ts": ts,
                        "author": author,
                        # "toc": html.toc_html if html.toc_html else "",
                        "toc": "", # just empty, toc generated by js but not python
                        "metadata": metadata,
                        "raw": content
                    }
            else:
                result["htmls"][file] = None
        result['ok'] = True
        return result
    
    def on_parse_pages(self, files):
        result = self.on_parse_files(files)
        return result

    
    def on_add_html_header_items(self, type_name):
        items = []
        items.append('<meta name="markdown-generator" content="teedoc-plugin-markdown-parser">')
        if self.config["mathjax"]["enable"]:
            items.append('''<script>
MathJax = {};
</script>'''.format(json.dumps(self.config["mathjax"]["config"])))
            items.append('<script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>')
            items.append('<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/{}.js"></script>'.format(self.config["mathjax"]["file_name"]))
        return items

    def _update_link(self, content):
        def re_del(c):
            ret = c[0]
            links = re.findall('\((.*?)\)', c[0])
            if len(links) > 0:
                for link in links:
                    if link.startswith(".") or os.path.isabs(link):
                        ret = re.sub("README.md", "index.html", c[0], flags=re.I)
                        ret = re.sub(r".md", ".html", ret, re.I)
                        return ret
            return ret
        def re_del_ipynb(c):
            ret = c[0]
            links = re.findall('\((.*?)\)', c[0])
            if len(links) > 0:
                for link in links:
                    if link.startswith(".") or os.path.isabs(link):
                        ret = re.sub("README.ipynb", "index.html", c[0], flags=re.I)
                        ret = re.sub(r".ipynb", ".html", ret, re.I)
                        return ret
            return ret
        # <a class="anchor-link" href="#&#38142;&#25509;"> </a></h2><p><a href="./syntax_markdown.md">markdown 语法</a>
        content = re.sub(r'\[.*?\]\(.*?\.md\)', re_del, content, flags=re.I)
        content = re.sub(r'\[.*?\]\(.*?\.ipynb\)', re_del_ipynb, content, flags=re.I)
        return content

if __name__ == "__main__":
    config = {
    }
    plug = Plugin(config=config)
    res = plug.parse_files(["md_files/basic.md"])
    print(res)
    if not os.path.exists("out"):
        os.makedirs("out")
    for file, html in res["htmls"].items():
        if html:
            file = "{}.html".format(os.path.splitext(os.path.basename(file))[0])
            with open(os.path.join("out", file), "w") as f:
                f.write(html)

