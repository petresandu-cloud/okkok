# fastlane-plugin-okkok

Runs the Okkok store compliance check from a fastlane lane, on the package the
lane just built, and fails the lane on findings that block submission.

```ruby
lane :beta do
  build_app(scheme: "Runner")          # or gradle(task: "assembleRelease")
  okkok(app_dir: ".", fail_on: "block")
  upload_to_testflight
end
```

Needs Python 3.11+ and `pip install okkok`. The plugin only shells out; every
verdict and its provenance come from the tool, never from Ruby. This directory
is the plugin's source; it is published as its own gem from here.
