def merge_backend_and_implementation(implementation_spec: dict, backend_spec: dict) -> dict:
    impl_modules = implementation_spec.get("implementation_spec", {}).get("modules", {})
    backend_modules = backend_spec.get("backend", {}).get("modules", {})

    for module_name, backend_module in backend_modules.items():
        impl_module = impl_modules.get(module_name)
        if not impl_module:
            continue

        impl_methods = impl_module.get("methods", {})
        backend_methods = backend_module.get("methods", {})

        for method_key, backend_method in backend_methods.items():
            impl_method = impl_methods.get(method_key)
            if not impl_method:
                continue

            # Fields allowed to be merged from implementation_spec
            for field in [
                "purpose",
                "trigger",
                "steps",
                "built_in_operations",
                "entity_interactions"
            ]:
                if field in impl_method:
                    backend_method[field] = impl_method[field]

    return backend_spec
