# Copyright (C) 2026 Editerra AB. SPDX-License-Identifier: AGPL-3.0-or-later
require "fastlane/plugin/okkok/version"

module Fastlane
  module Okkok
    def self.all_classes
      Dir[File.expand_path("**/{actions,helper}/*.rb", File.dirname(__FILE__))]
    end
  end
end

Fastlane::Okkok.all_classes.each { |f| require f }
