#!/bin/bash

requirenments_file=${1:-requirements.github}

download_release () {
  github_token=${GITHUB_TOKEN}

  echo "github_token: "$github_token

  base_url=https://github.com
  org=$1
  rep=$2
  version=$3
  file_name=$4

  echo "Downloading: $base_url/$org/$rep/archive/$version.zip"

  curl -L -o "$file_name"\
        -H "Accept: application/vnd.github.v3.raw"\
        -H "Authorization: token $github_token"\
        $base_url/$org/$rep/archive/$version.zip
}

while IFS= read -r line || [[ -n "$line" ]]; do
  read -r org rep version <<<$(IFS=" "; echo $line)
  package_archive="$rep-$version.zip"
  download_release "$org" "$rep" "$version" "$package_archive"

  if [ ! -f "$package_archive" ]; then
    echo "Download failed, check GITHUB_TOKEN environment variable"
    exit 1
  fi

  unzip "$package_archive"
  package_dir=$rep-$version
  cd "$package_dir"
  chmod 0755 install.sh
  ./install.sh
  cd ../
  rm -rf "$package_dir"
  rm -rf "$package_archive"
done <"$requirenments_file"