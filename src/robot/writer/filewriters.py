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

import ast

from robot.parsing.lexer import Token

from .formatters import TxtFormatter, PipeFormatter


def FileWriter(context):
    """Creates and returns a ``FileWriter`` object.

    :param context: The type of the returned ``FileWriter`` is determined based
        on ``context.format``. ``context`` is also passed to created writer.
    :type context: :class:`~robot.writer.datafilewriter.WritingContext`
    """
    if context.pipe_separated:
        return PipeSeparatedTxtWriter(context)
    return SpaceSeparatedTxtWriter(context)


class ColumnAligner(ast.NodeVisitor):

    def __init__(self, widths):
        self.widths = widths
        self._test_name_len = 0
        self.indent = 0
        self._first_statment_seen = False

    def visit_TestOrKeyword(self, node):
        self._first_statment_seen = False
        self.generic_visit(node)

    def visit_ForLoop(self, statement):
        self.indent += 1
        self.generic_visit(statement)
        self.indent -= 1

    def visit_Statement(self, statement):
        if statement.type == Token.TESTCASE_HEADER:
            return
        if statement.type == Token.NAME:
            self._test_name_len = len(statement.tokens[0].value)
            return
        for line in statement.lines:
            line_pos = 0
            exp_pos = 0
            widths = self.widths[:]
            if self.indent > 0 and line[0].type == Token.KEYWORD:
                first_width = widths.pop(0)
                widths[0] = widths[0] + first_width
            for token, width in zip(line, widths):
                exp_pos += width
                if line_pos == 0 and not self._first_statment_seen and \
                        self._test_name_len < 18:
                    exp_pos -= self._test_name_len
                    self._first_statment_seen = True
                token.value = (exp_pos - line_pos) * ' ' + token.value
                line_pos += len(token.value)


class ColumnWidthCounter(ast.NodeVisitor):

    def __init__(self, widths):
        self.widths = widths
        self._name_width = 0
        self._first_line_seen = False

    def visit_Statement(self, statement):
        if statement.type == Token.NAME:
            self._name_width = len(statement.tokens[0].value)
            self._first_line_seen = False
            return
        if statement.type == Token.TESTCASE_HEADER:
            return
        for line in statement.lines:
            for index, token in enumerate(line):
                col = index + 1
                if col >= len(self.widths):
                    self.widths.append(len(token.value))
                elif len(token.value) > self.widths[col]:
                    self.widths[col] = len(token.value)
            self._first_line_seen = True


class Aligner(ast.NodeVisitor):
    _setting_and_variable_name_width = 14

    def visit_Section(self, section):
        if section.type in (Token.SETTING_HEADER, Token.VARIABLE_HEADER):
            self.generic_visit(section)
        elif section.type == Token.TESTCASE_HEADER:
            if len(section.header) > 1:
                widths = [len(t.value) for t in section.header]
                counter = ColumnWidthCounter(widths[:])
                counter.visit(section)
                ColumnAligner(counter.widths[:-1]).visit(section)

    def visit_Statement(self, statement):
        for line in statement.lines:
            line[0].value = line[0].value.ljust(
                self._setting_and_variable_name_width)


class SeparatorRemover(ast.NodeVisitor):

    def visit_Statement(self, statement):
        if statement.type == Token.TESTCASE_HEADER:
            self._add_whitespace_to_header_values(statement)
        statement.tokens = [t for t in statement.tokens
                            if t.type not in (Token.EOL, Token.SEPARATOR,
                                              Token.OLD_FOR_INDENT)]

    def _add_whitespace_to_header_values(self, statement):
        prev = None
        for token in statement.tokens:
            if token.type == Token.SEPARATOR and prev:
                prev.value += token.value[:-4] # TODO pipes??
            elif token.type == Token.TESTCASE_HEADER:
                prev = token
            else:
                prev = None


class SettingCleaner(ast.NodeVisitor):

    def visit_Statement(self, statement):
        if statement.type in Token.SETTING_TOKENS:
            name = statement.tokens[0].value
            if name.strip().startswith('['):
                cleaned = '[%s]' % name[1:-1].strip().lower().title()
            else:
                cleaned = name.lower().title()
            statement.tokens[0].value = cleaned


class ForLoopCleaner(ast.NodeVisitor):

    def visit_ForLoop(self, forloop):
        forloop.header[0].value = 'FOR'
        forloop.end[0].value = 'END'


class Writer(ast.NodeVisitor):

    def __init__(self, configuration):
        self.configuration = configuration
        self.output = configuration.output
        self.indent = 0
        self.pipes = configuration.pipe_separated
        self.separator = ' ' * configuration.txt_separating_spaces if not self.pipes else ' | '
        self.indent_marker = self.separator if not self.pipes else '   | '
        self._section_seen = False
        self._test_or_kw_seen = False
        self._test_case_section_headers = None

    def visit_Statement(self, statement):
        self._write_statement(statement)

    def visit_Section(self, section):
        if self._section_seen:
            self.output.write('\n')
        if section.type == Token.TESTCASE_HEADER:
            if len(section.header) > 1:
                self._test_case_section_headers = [len(t.value) for t
                                                   in section.header]
        self.generic_visit(section)
        self._section_seen = True
        self._test_or_kw_seen = False
        self._test_case_section_headers = False

    def visit_TestOrKeyword(self, node):
        if self._test_or_kw_seen:
            self.output.write('\n')
        self._write_statement(node.name, write_newline=(
                not self._test_case_section_headers or
                len(node.name.tokens[0].value) >= 18))
        self.indent += 1
        self.generic_visit(node.body)
        self.indent -= 1
        self._test_or_kw_seen = True

    def visit_ForLoop(self, node):
        self._write_statement(node.header)
        self.indent += 1
        self.generic_visit(node.body)
        self.indent -= 1
        self._write_statement(node.end)

    def _write_statement(self, statement, write_newline=True):
        indent = self.indent * self.indent_marker
        for line in statement.lines:
            values = [t.value for t in line]
            row = indent + self.separator.join(values)
            if self.pipes:
                row = '| ' + row + ' |'
            else:
                row = row.rstrip()
            self.output.write(row)
            if write_newline:
                self.output.write('\n')


class _DataFileWriter(object):

    def __init__(self, configuration):
        self.config = configuration
        self._output = configuration.output

    def write(self, model):
        SeparatorRemover().visit(model)
        SettingCleaner().visit(model)
        ForLoopCleaner().visit(model)
        Aligner().visit(model)
        Writer(self.config).visit(model)

    def _write_rows(self, rows):
        for row in rows:
            self._write_row(row)

    def _write_empty_row(self, table):
        self._write_row(self._formatter.empty_row_after(table))

    def _write_row(self, row):
        raise NotImplementedError

    def _write_section(self, section, is_last):
        self._write_rows(self._formatter.format_section(section))
        if not is_last:
            self._write_empty_row(section)


class SpaceSeparatedTxtWriter(_DataFileWriter):

    def __init__(self, configuration):
        self._separator = ' ' * configuration.txt_separating_spaces
        _DataFileWriter.__init__(self, configuration)

    def _write_row(self, row):
        line = self._separator.join(t.value for t in row).rstrip() + '\n'
        self._output.write(line)


class PipeSeparatedTxtWriter(_DataFileWriter):
    _separator = ' | '

    def __init__(self, configuration):
        _DataFileWriter.__init__(self, configuration)

    def _write_row(self, row):
        row = self._separator.join(t.value for t in row)
        if row:
            row = '| ' + row + ' |'
        self._output.write(row + '\n')
