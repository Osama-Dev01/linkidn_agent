


export function fieldsOf(page) {
  if (page.fields) {
    return page.fields;
  }

  const fields = [];

  for (const group of page.groups) {
    fields.push(...group.fields);
  }

  return fields;
}

export function visible(key, data) {
  if (key === 'recency_window') {
    const isTimely = data.freshness === 'Timely';
    const isBalanced = data.freshness === 'Balanced';

    return isTimely || isBalanced;
  }

  if (key === 'word_range') {
    return data.post_length === 'Custom';
  }

  if (key === 'hashtag_max') {
    return data.hashtags === 'Limited';
  }

  return true;
}

export function required(field, data) {
  if (field.required) {
    return field.required;
  }

  const conditionalFields = [
    'recency_window',
    'word_range',
    'hashtag_max',
  ];

  if (conditionalFields.includes(field.key)) {
    return visible(field.key, data);
  }

  return false;
}

export const limits = {
  recency_window: [1, 365],
  minimum_sources: [1, 20],
  hashtag_max: [0, 30],
  cooldown_days: [0, 3650],
};

export function validateFields(fields, data) {
  const errors = {};

  for (const field of fields) {
    if (!visible(field.key, data)) {
      continue;
    }

    const value = data[field.key];

    let empty = false;

    if (value === null || value === undefined) {
      empty = true;
    } else if (Array.isArray(value)) {
      const hasNonEmptyItem = value.some(function (item) {
        const text = String(item);
        const trimmedText = text.trim();

        return trimmedText.length > 0;
      });

      empty = !hasNonEmptyItem;
    } else {
      const text = String(value);
      const trimmedText = text.trim();

      empty = trimmedText.length === 0;
    }

    if (empty) {
      if (required(field, data)) {
        errors[field.key] = 'Please enter a value or select an option.';
      }

      continue;
    }

    if (field.type === 'number') {
      const [min, max] = limits[field.key];

      const isWholeNumber = Number.isInteger(value);
      const isBelowMinimum = value < min;
      const isAboveMaximum = value > max;

      if (!isWholeNumber || isBelowMinimum || isAboveMaximum) {
        errors[field.key] = `Enter a whole number from ${min} to ${max}.`;
      }
    } else if (Array.isArray(value)) {
      const hasTooManyEntries = value.length > 50;

      const hasInvalidEntry = value.some(function (item) {
        const trimmedItem = item.trim();
        const isEmpty = trimmedItem.length === 0;
        const isTooLong = item.length > 300;

        return isEmpty || isTooLong;
      });

      if (hasTooManyEntries || hasInvalidEntry) {
        errors[field.key] =
          'Use up to 50 non-empty entries, each under 300 characters.';
      }

      if (field.type === 'multi') {
        const hasUnavailableOption = value.some(function (item) {
          return !field.options.includes(item);
        });

        if (hasUnavailableOption) {
          errors[field.key] = 'Choose one of the available options.';
        }
      }
    } else {
      const isChoiceField = field.type === 'choice';
      const isSelectField = field.type === 'select';

      let hasUnavailableOption = false;

      if (isChoiceField || isSelectField) {
        hasUnavailableOption = !field.options.includes(value);
      }

      if (hasUnavailableOption) {
        errors[field.key] = 'Choose one of the available options.';
      } else {
        const text = String(value);

        if (text.length > 10000) {
          errors[field.key] = 'Keep this under 10,000 characters.';
        }
      }
    }
  }

  if (data.content_themes) {
    const themeCount = data.content_themes.length;

    if (themeCount < 3 || themeCount > 6) {
      errors.content_themes = 'Choose 3–6 themes.';
    }
  }

  if (data.post_length === 'Custom') {
    const rangePattern = /^(\d+)\s*-\s*(\d+)$/;
    const wordRange = data.word_range || '';
    const range = rangePattern.exec(wordRange);

    if (!range) {
      errors.word_range =
        'Use a range such as 100-200 (maximum 10000).';
    } else {
      const minimumWords = Number(range[1]);
      const maximumWords = Number(range[2]);

      const isBelowMinimum = minimumWords < 1;
      const isReversed = minimumWords > maximumWords;
      const isAboveMaximum = maximumWords > 10000;

      if (isBelowMinimum || isReversed || isAboveMaximum) {
        errors.word_range =
          'Use a range such as 100-200 (maximum 10000).';
      }
    }
  }

  return errors;
}

export function validatePage(page, data) {
  if (page.repeat) {
    const items = data.items || [];

    if (items.length > 20) {
      return {
        _page: 'Add up to 20 records.',
      };
    }

    const errors = {};

    for (let index = 0; index < items.length; index += 1) {
      const item = items[index];
      const itemErrors = validateFields(page.fields, item);
      const errorEntries = Object.entries(itemErrors);

      for (const [key, message] of errorEntries) {
        const errorKey = `${index}.${key}`;

        errors[errorKey] = message;
      }
    }

    return errors;
  }

  const fields = fieldsOf(page);
  const errors = validateFields(fields, data);

  if (page.key === 'expertise') {
    const hasExperiencedTopics = Boolean(data.experienced_topics?.length);
    const hasLearningTopics = Boolean(data.learning_topics?.length);

    if (!hasExperiencedTopics && !hasLearningTopics) {
      errors.experienced_topics = 'Add an experienced or learning topic.';
    }
  }

  return errors;
}

export function payload(page, data) {
  function clean(record) {
    const fields = fieldsOf(page);
    const cleanedRecord = {};

    for (const field of fields) {
      if (!visible(field.key, record)) {
        continue;
      }

      let value = record[field.key];

      if (Array.isArray(value)) {
        const trimmedItems = value.map(function (item) {
          return item.trim();
        });

        value = trimmedItems.filter(Boolean);
      } else if (typeof value === 'string') {
        value = value.trim();
      }

      if (value === undefined || value === null || value === '') {
        continue;
      }

      cleanedRecord[field.key] = value;
    }

    return cleanedRecord;
  }

  if (page.repeat) {
    const items = data.items || [];

    const cleanedItems = items.map(function (item) {
      const cleanedRecord = clean(item);

      return {
        id: item.id,
        ...cleanedRecord,
      };
    });

    return {
      items: cleanedItems,
    };
  }

  return clean(data);
}