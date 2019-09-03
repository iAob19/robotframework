#  Copyright 2008-2015 Nokia Networks
#  Copyright 2016-     Robot Framework Foundation
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import re

from robot.parsing.lexer import Token
from .aligners import FirstColumnAligner, ColumnAligner, NullAligner


class _DataFileFormatter(object):
    _whitespace = re.compile('\s{2,}')
    _split_multiline_doc = True

    def __init__(self, column_count):
        self._column_count = column_count

    def _want_names_on_first_content_row(self, table, name):
        return True

    def empty_row_after(self, table):
        return self._format_row([], table)

    def format_section(self, section):
        formatted = []
        for s in self._format_statement(section, section, recurse=False):
            formatted.append(s)
        has_test_or_kw = False
        for statement in section.statements:
            if has_test_or_kw and statement.tokens[0].type == Token.NAME:
                formatted.append([Token(Token.SEPARATOR, '')])
            if len(statement.tokens) == 1 and statement.tokens[0].type == Token.EOL:
                continue
            for row in self._format_statement(section, statement):
                formatted.append(self._indent(section, row))
            if statement.tokens[0].type == Token.NAME:
                has_test_or_kw = True
        aligner = self._aligner_for(section, formatted)
        return [aligner.align_row(row) for row in formatted]

    def _should_split_rows(self, table):
        return not self._should_align_columns(table)

    def _split_rows(self, original_rows, table):
        for original in original_rows:
            for split in self._splitter.split(original, table.type):
                yield split

    def _should_align_columns(self, section):
        return self._is_indented_table(section) and len(section.header.tokens) > 2

    def _is_indented_table(self, section):
        return section is not None and section.type in [Token.TESTCASE_HEADER,
                                                        Token.KEYWORD_HEADER]

    def _escape_consecutive_whitespace(self, row):
        return [self._whitespace.sub(self._whitespace_escaper,
                                     cell.replace('\n', ' ')) for cell in row]

    def _whitespace_escaper(self, match):
        return '\\'.join(match.group(0))

    def _format_row(self, row, table=None):
        raise NotImplementedError

    def _format_header(self, header, table):
        raise NotImplementedError

    def _format_statement(self, section, statement, recurse=True):
        raise NotImplementedError


class TxtFormatter(_DataFileFormatter):
    _test_or_keyword_name_width = 18
    _setting_and_variable_name_width = 14

    def _format_statement(self, section, statement, recurse=True):
        return list(self._split_to_rows(section, statement, recurse))

    def _indent(self, section, statement):
        if section.type in [Token.TESTCASE_HEADER, Token.KEYWORD_HEADER] \
                and statement[0].type != Token.NAME:
            return [self._empty_token()] + statement
        return statement

    def _format_row(self, row, section=None):
        return row

    def _aligner_for(self, section, rows):
        if section.type in [Token.SETTING_HEADER, Token.VARIABLE_HEADER]:
            return FirstColumnAligner(self._setting_and_variable_name_width)
        if self._should_align_columns(section):
            return ColumnAligner(self._test_or_keyword_name_width, rows)
        return NullAligner()

    def _format_header(self, header, section):
        header = ['*** %s ***' % header[0]] + header[1:]
        aligner = self._aligner_for(section)
        return aligner.align_row(header)

    def _want_names_on_first_content_row(self, section, name):
        return self._should_align_columns(section) and \
               len(name) <= self._test_or_keyword_name_width

    def _escape(self, row):
        if not row:
            return row
        return list(
            self._escape_cells(self._escape_consecutive_whitespace(row)))

    def _escape_cells(self, row):
        escape = False
        for cell in row:
            if cell:
                escape = True
            elif escape:
                cell = '\\'
            yield cell

    def _split_to_rows(self, section, statement, recurse=False):
        tokens_on_row = []
        for_seen = False
        in_for_loop = False
        prev_t = None
        for t in self._get_tokens(statement, recurse):
            if t.type == Token.END:
                for_seen = in_for_loop = False
            if for_seen and t.type == Token.KEYWORD:
                in_for_loop = True
            if t.type == t.SEPARATOR:
                continue
            if t.type == t.EOL:
                if not (prev_t and prev_t.type == Token.NAME and
                        self._want_names_on_first_content_row(section, prev_t.value)):
                    if tokens_on_row:
                        yield tokens_on_row if not in_for_loop else [self._empty_token()] + tokens_on_row
                    tokens_on_row = []
                continue
            if t.type == t.CONTINUATION:
                if tokens_on_row:
                    yield tokens_on_row if not in_for_loop else [
                                                                    self._empty_token()] + tokens_on_row
                tokens_on_row = [t]
            else:
                tokens_on_row.append(t)
            if not for_seen:
                for_seen = t.type == Token.FOR
            prev_t = t
        if tokens_on_row:
            yield tokens_on_row if not in_for_loop else [
                                                            self._empty_token()] + tokens_on_row

    def _get_tokens(self, statement, recurse):
        for t in statement.tokens:
            yield t
        if recurse:
            for s in statement.statements:
                for t in s.tokens:
                    yield t

    def _empty_token(self):
        return Token(Token.SEPARATOR, '')


class PipeFormatter(TxtFormatter):

    def _escape_cells(self, row):
        return [self._escape_empty(self._escape_pipes(cell)) for cell in row]

    def _escape_empty(self, cell):
        return cell or '  '

    def _escape_pipes(self, cell):
        if ' | ' in cell:
            cell = cell.replace(' | ', ' \\| ')
        if cell.startswith('| '):
            cell = '\\' + cell
        if cell.endswith(' |'):
            cell = cell[:-1] + '\\|'
        return cell

    def _empty_token(self):
        return Token(Token.SEPARATOR, '  ')
