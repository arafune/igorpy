# Copyright (C) 2012 W. Trevor King <wking@tremily.us>
#
# This file is part of igor.
#
# igor is free software: you can redistribute it and/or modify it under the
# terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# igor is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with igor.  If not, see <http://www.gnu.org/licenses/>.

# Memo essentially No diff with igor2

import io

from .. import LOG
from ..binarywave import TYPE_TABLE
from ..binarywave import NullStaticStringField
from ..binarywave import DynamicStringField
from ..struct import Structure
from ..struct import DynamicStructure
from ..struct import Field
from ..struct import DynamicField
from ..util import byte_order as _byte_order
from ..util import need_to_reorder_bytes as _need_to_reorder_bytes
from .base import Record


class ListedStaticStringField(NullStaticStringField):
    """Handle string conversions for multi-count dynamic parents.

    If a field belongs to a multi-count dynamic parent, the parent is
    called multiple times to parse each count, and the field's
    post-unpack hook gets called after the field is unpacked during
    each iteration.  This requires alternative logic for getting and
    setting the string data.  The actual string formatting code is not
    affected.
    """

    def post_unpack(self, parents, data):
        parent_structure = parents[-1]
        parent_data = self._get_structure_data(parents, data, parent_structure)
        d = self._normalize_string(parent_data[-1][self.name])
        parent_data[-1][self.name] = d


class ListedDynamicStrDataField(DynamicStringField, ListedStaticStringField):
    _size_field = "strLen"
    _null_terminated = False

    def _get_size_data(self, parents, data):
        parent_structure = parents[-1]
        parent_data = self._get_structure_data(parents, data, parent_structure)
        return parent_data[-1][self._size_field]


class DynamicVarDataField(DynamicField):
    def __init__(self, *args, **kwargs):
        if "array" not in kwargs:
            kwargs["array"] = True
        super().__init__(*args, **kwargs)

    def pre_pack(self, parents, data):
        raise NotImplementedError()

    def post_unpack(self, parents, data):
        var_structure = parents[-1]
        var_data = self._get_structure_data(parents, data, var_structure)
        data = var_data[self.name]
        d = {}
        for i, value in enumerate(data):
            key, value = self._normalize_item(i, value)
            d[key] = value
        var_data[self.name] = d

    def _normalize_item(self, index, value):
        raise NotImplementedError()


class DynamicSysVarField(DynamicVarDataField):
    def _normalize_item(self, index, value):
        name = f"K{index}"
        return (name, value)


class DynamicUserVarField(DynamicVarDataField):
    def _normalize_item(self, index, value):
        name = value["name"]
        value = value["num"]
        return (name, value)


class DynamicUserStrField(DynamicVarDataField):
    def _normalize_item(self, index, value):
        name = value["name"]
        value = value["data"]
        return (name, value)


class DynamicVarNumField(DynamicField):
    def post_unpack(self, parents, data):
        parent_structure = parents[-1]
        parent_data = self._get_structure_data(parents, data, parent_structure)
        d = self._normalize_numeric_variable(parent_data[-1][self.name])
        parent_data[-1][self.name] = d

    def _normalize_numeric_variable(self, num_var):
        t = TYPE_TABLE[num_var["numType"]]
        if num_var["numType"] % 2:  # complex number
            return t(complex(num_var["realPart"], num_var["imagPart"]))
        else:
            return t(num_var["realPart"])


class DynamicFormulaField(DynamicStringField):
    _size_field = "formulaLen"
    _null_terminated = True


# From Variables.h
VarHeader1 = Structure(  # `version` field pulled out into VariablesRecord
    name="VarHeader1",
    fields=[
        Field("h", "numSysVars", help="Number of system variables (K0, K1, ...)."),
        Field(
            "h", "numUserVars", help="Number of user numeric variables -- may be zero."
        ),
        Field(
            "h", "numUserStrs", help="Number of user string variables -- may be zero."
        ),
    ],
)

# From Variables.h
VarHeader2 = Structure(  # `version` field pulled out into VariablesRecord
    name="VarHeader2",
    fields=[
        Field("h", "numSysVars", help="Number of system variables (K0, K1, ...)."),
        Field(
            "h", "numUserVars", help="Number of user numeric variables -- may be zero."
        ),
        Field(
            "h", "numUserStrs", help="Number of user string variables -- may be zero."
        ),
        Field(
            "h",
            "numDependentVars",
            help="Number of dependent numeric variables -- may be zero.",
        ),
        Field(
            "h",
            "numDependentStrs",
            help="Number of dependent string variables -- may be zero.",
        ),
    ],
)

# From Variables.h
UserStrVarRec1 = DynamicStructure(
    name="UserStrVarRec1",
    fields=[
        ListedStaticStringField(
            "c", "name", help="Name of the string variable.", count=32
        ),
        Field("h", "strLen", help="The real size of the following array."),
        ListedDynamicStrDataField("c", "data"),
    ],
)

# From Variables.h
UserStrVarRec2 = DynamicStructure(
    name="UserStrVarRec2",
    fields=[
        ListedStaticStringField(
            "c", "name", help="Name of the string variable.", count=32
        ),
        Field("l", "strLen", help="The real size of the following array."),
        Field("c", "data"),
    ],
)

# From Variables.h
VarNumRec = Structure(
    name="VarNumRec",
    fields=[
        Field("h", "numType", help="Type from binarywave.TYPE_TABLE"),
        Field("d", "realPart", help="The real part of the number."),
        Field("d", "imagPart", help="The imag part if the number is complex."),
        Field("l", "reserved", help="Reserved - set to zero."),
    ],
)

# From Variables.h
UserNumVarRec = DynamicStructure(
    name="UserNumVarRec",
    fields=[
        ListedStaticStringField(
            "c", "name", help="Name of the string variable.", count=32
        ),
        Field("h", "type", help="0 = string, 1 = numeric."),
        DynamicVarNumField(
            VarNumRec,
            "num",
            help="Type and value of the variable if it is numeric. Not used for string.",
        ),
    ],
)

# From Variables.h
UserDependentVarRec = DynamicStructure(
    name="UserDependentVarRec",
    fields=[
        ListedStaticStringField(
            "c", "name", help="Name of the string variable.", count=32
        ),
        Field("h", "type", help="0 = string, 1 = numeric."),
        Field(
            VarNumRec,
            "num",
            help="Type and value of the variable if it is numeric.  Not used for string.",
        ),
        Field("h", "formulaLen", help="The length of the dependency formula."),
        DynamicFormulaField(
            "c",
            "formula",
            help="Start of the dependency formula. A C string including null terminator.",
        ),
    ],
)


class DynamicVarHeaderField(DynamicField):
    def pre_pack(self, parents, data):
        raise NotImplementedError()

    def post_unpack(self, parents, data):
        var_structure = parents[-1]
        var_data = self._get_structure_data(parents, data, var_structure)
        data = var_data["var_header"]
        sys_vars_field = var_structure.get_field("sysVars")
        sys_vars_field.count = data["numSysVars"]
        sys_vars_field.setup()
        user_vars_field = var_structure.get_field("userVars")
        user_vars_field.count = data["numUserVars"]
        user_vars_field.setup()
        user_strs_field = var_structure.get_field("userStrs")
        user_strs_field.count = data["numUserStrs"]
        user_strs_field.setup()
        if "numDependentVars" in data:
            dependent_vars_field = var_structure.get_field("dependentVars")
            dependent_vars_field.count = data["numDependentVars"]
            dependent_vars_field.setup()
            dependent_strs_field = var_structure.get_field("dependentStrs")
            dependent_strs_field.count = data["numDependentStrs"]
            dependent_strs_field.setup()
        var_structure.setup()


Variables1 = DynamicStructure(
    name="Variables1",
    fields=[
        DynamicVarHeaderField(VarHeader1, "var_header", help="Variables header"),
        DynamicSysVarField("f", "sysVars", help="System variables", count=0),
        DynamicUserVarField(
            UserNumVarRec, "userVars", help="User numeric variables", count=0
        ),
        DynamicUserStrField(
            UserStrVarRec1, "userStrs", help="User string variables", count=0
        ),
    ],
)


Variables2 = DynamicStructure(
    name="Variables2",
    fields=[
        DynamicVarHeaderField(VarHeader2, "var_header", help="Variables header"),
        DynamicSysVarField("f", "sysVars", help="System variables", count=0),
        DynamicUserVarField(
            UserNumVarRec, "userVars", help="User numeric variables", count=0
        ),
        DynamicUserStrField(
            UserStrVarRec2, "userStrs", help="User string variables", count=0
        ),
        Field(
            UserDependentVarRec,
            "dependentVars",
            help="Dependent numeric variables.",
            count=0,
            array=True,
        ),
        Field(
            UserDependentVarRec,
            "dependentStrs",
            help="Dependent string variables.",
            count=0,
            array=True,
        ),
    ],
)


class DynamicVersionField(DynamicField):
    def pre_pack(self, parents, byte_order):
        raise NotImplementedError()

    def post_unpack(self, parents, data):
        variables_structure = parents[-1]
        variables_data = self._get_structure_data(parents, data, variables_structure)
        version = variables_data["version"]
        if variables_structure.byte_order in "@=":
            need_to_reorder_bytes = _need_to_reorder_bytes(version)
            variables_structure.byte_order = _byte_order(need_to_reorder_bytes)
            LOG.debug(
                "get byte order from version: {} (reorder? {})".format(
                    variables_structure.byte_order, need_to_reorder_bytes
                )
            )
        else:
            need_to_reorder_bytes = False

        old_format = variables_structure.fields[-1].format
        if version == 1:
            variables_structure.fields[-1].format = Variables1
        elif version == 2:
            variables_structure.fields[-1].format = Variables2
        elif not need_to_reorder_bytes:
            raise ValueError(f"invalid variables record version: {version}")

        if variables_structure.fields[-1].format != old_format:
            LOG.debug(
                "change variables record from {} to {}".format(
                    old_format, variables_structure.fields[-1].format
                )
            )
            variables_structure.setup()
        elif need_to_reorder_bytes:
            variables_structure.setup()

        # we might need to unpack again with the new byte order
        return need_to_reorder_bytes


VariablesRecordStructure = DynamicStructure(
    name="VariablesRecord",
    fields=[
        DynamicVersionField("h", "version", help="Version number for this header."),
        Field(Variables1, "variables", help="The rest of the variables data."),
    ],
)


class VariablesRecord(Record):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.header['version']  # record version always 0?
        VariablesRecordStructure.byte_order = "="
        VariablesRecordStructure.setup()
        stream = io.BytesIO(bytes(self.data))
        self.variables = VariablesRecordStructure.unpack_stream(stream)
        self.namespace = {}
        for key, value in self.variables["variables"].items():
            if key not in ["var_header"]:
                LOG.debug(
                    "update namespace {} with {} for {}".format(
                        self.namespace, value, key
                    )
                )
                self.namespace.update(value)
