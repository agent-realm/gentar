// Pinned: must equal baml-py's version in coordinator/requirements.txt
// (a test checks). The generated client is committed under
// gentar/baml_client; regenerate with `baml-cli generate` after any edit here.
generator target {
  output_type "python/pydantic"
  output_dir "../gentar"
  version "0.226.2"
  default_client_mode "sync"
}
