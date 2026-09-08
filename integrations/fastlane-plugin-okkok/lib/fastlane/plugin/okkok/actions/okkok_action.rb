# Copyright (C) 2026 Editerra AB. SPDX-License-Identifier: AGPL-3.0-or-later
require "fastlane/action"
require "json"

module Fastlane
  module Actions
    class OkkokAction < Action
      def self.run(params)
        app_dir = File.expand_path(params[:app_dir])
        cmd = ["okkok", "audit", app_dir]
        cmd << "--offline" if params[:offline]
        (params[:stated_stage] || []).each { |s| cmd += ["--stated-stage", s] }
        cmd += ["--stated-by", "fastlane"]
        UI.message("Okkok: #{cmd.join(' ')}")
        system(*cmd)
        grid = JSON.parse(File.read(File.join(app_dir, "okkok", "grid.json")))
        counts = grid["counts"]
        fail = counts["FAIL"] || 0
        risk = counts["RISK"] || 0
        UI.message("Okkok: #{fail} block submission, #{risk} likely to be questioned; report at #{File.join(app_dir, 'okkok', 'report.html')}")
        grid["rows"].each do |r|
          UI.important("#{r['title']} (#{r['store']}): #{r['evidence'][0, 240]}") if %w[FAIL RISK].include?(r["verdict"])
        end
        case params[:fail_on]
        when "block" then UI.user_error!("Okkok: #{fail} finding(s) block submission") if fail > 0
        when "risk" then UI.user_error!("Okkok: #{fail} blocking and #{risk} risk finding(s)") if fail + risk > 0
        end
        counts
      end

      def self.description
        "Audit the built app against the App Store and Google Play rules with Okkok"
      end

      def self.authors
        ["Editerra AB"]
      end

      def self.available_options
        [
          FastlaneCore::ConfigItem.new(key: :app_dir, description: "Directory holding the built package and okkok/listing.toml", default_value: "."),
          FastlaneCore::ConfigItem.new(key: :offline, description: "Skip network: rule-page sweep, store lookups, consoles", type: Boolean, default_value: false),
          FastlaneCore::ConfigItem.new(key: :stated_stage, description: "e.g. ['apple=in-review']", type: Array, optional: true),
          FastlaneCore::ConfigItem.new(key: :fail_on, description: "block, risk or none", default_value: "block")
        ]
      end

      def self.is_supported?(platform)
        [:ios, :android].include?(platform)
      end
    end
  end
end
