# Copyright (C) 2026 Editerra AB. SPDX-License-Identifier: AGPL-3.0-or-later
lib = File.expand_path("lib", __dir__)
$LOAD_PATH.unshift(lib) unless $LOAD_PATH.include?(lib)
require "fastlane/plugin/okkok/version"

Gem::Specification.new do |spec|
  spec.name          = "fastlane-plugin-okkok"
  spec.version       = Fastlane::Okkok::VERSION
  spec.authors       = ["Editerra AB"]
  spec.email         = ["contact@editerra.se"]
  spec.summary       = "Run the Okkok store compliance check from a fastlane lane"
  spec.homepage      = "https://github.com/petresandu-cloud/okkok"
  spec.license       = "AGPL-3.0-or-later"
  spec.files         = Dir["lib/**/*"] + %w[README.md]
  spec.required_ruby_version = ">= 2.6"
  spec.add_development_dependency "fastlane", ">= 2.200.0"
end
