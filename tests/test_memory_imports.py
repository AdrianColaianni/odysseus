"""Regression tests for memory import-path compatibility."""


def test_services_memory_manager_is_canonical_src_class():
    from services.memory import MemoryManager as package_manager
    from services.memory.memory import MemoryManager as module_manager
    from src.memory import MemoryManager as canonical_manager

    assert module_manager is canonical_manager
    assert package_manager is canonical_manager
    assert hasattr(package_manager, "increment_uses")
    assert hasattr(package_manager, "claim_ownerless")


def test_services_memory_vector_is_canonical_src_class():
    from services.memory import MemoryVectorStore as package_vector_store
    from services.memory.memory_vector import MemoryVectorStore as module_vector_store
    from src.memory_vector import MemoryVectorStore as canonical_vector_store

    assert module_vector_store is canonical_vector_store
    assert package_vector_store is canonical_vector_store


def test_canonical_manager_keeps_ownerless_claim_helper(tmp_path):
    from src.memory import MemoryManager

    manager = MemoryManager(str(tmp_path / "memory.json"))
    entry = manager.add_entry("User likes compact code reviews")
    manager.save([entry])

    manager.claim_ownerless("alice")

    memories = manager.load_all()
    assert memories[0]["owner"] == "alice"
