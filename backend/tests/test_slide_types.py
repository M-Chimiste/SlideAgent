from app.services import slide_types as st
from app.services.pptx_native.primitives import BUILDERS
from app.services.slide_design import fit


def test_every_type_pins_to_a_real_primitive():
    for t in st.SLIDE_TYPES.values():
        assert t.primitive in BUILDERS, f"{t.key} -> unknown native primitive {t.primitive}"
        # and the primitive has a capacity contract
        assert isinstance(t.budget(), fit.PrimitiveCapacity)


def test_archetype_map_values_are_valid_types():
    for archetype, type_key in st.ARCHETYPE_TO_TYPE.items():
        assert type_key in st.SLIDE_TYPES, f"{archetype} -> unknown type {type_key}"


def test_archetype_map_matches_existing_specs_mapping():
    # Guards against drift from planning/specs._slide_type_for_archetype.
    from app.services.content_planner import ContentPlanner

    planner = ContentPlanner()
    for archetype, expected in st.ARCHETYPE_TO_TYPE.items():
        assert planner._slide_type_for_archetype(archetype) == expected


def test_list_and_non_list_partition_all_types():
    assert st.LIST_TYPES | st.NON_LIST_TYPES == set(st.SLIDE_TYPES)
    assert not (st.LIST_TYPES & st.NON_LIST_TYPES)
    # the new non-list single-idea kinds exist
    for key in ("stat", "statement", "deep_dive"):
        assert key in st.SLIDE_TYPES and key in st.NON_LIST_TYPES


def test_statement_types_are_roomy_non_list():
    for key in st.STATEMENT_TYPES:
        t = st.get_slide_type(key)
        assert not t.is_list


def test_unknown_type_falls_back_to_content():
    assert st.get_slide_type("nope").key == "content"
    assert st.slide_type_for_archetype("nope") == "content"
    assert st.is_list_type("content") and not st.is_list_type("stat")
